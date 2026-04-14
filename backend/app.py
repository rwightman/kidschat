"""
KidsChat — FastAPI entry point.
Serves the web UI and handles WebSocket connections for real-time voice chat.
"""

from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
from typing import cast

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from backend.orchestrator import Orchestrator

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("kidschat")

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
BASE = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=BASE / "frontend" / "templates")

DEFAULT_TALKING_HEAD_CHARACTER = "julia"
TALKING_HEAD_AVATAR_PRESETS = {
    "julia": {
        "url": "/static/avatars/julia.glb",
        "body": "F",
    },
    "mpfb": {
        "url": "https://raw.githubusercontent.com/met4citizen/TalkingHead/main/avatars/mpfb.glb",
        "body": "F",
    },
    "brunette": {
        "url": "https://raw.githubusercontent.com/met4citizen/TalkingHead/main/avatars/brunette.glb",
        "body": "F",
    },
    "brunette-t": {
        "url": "https://raw.githubusercontent.com/met4citizen/TalkingHead/main/avatars/brunette-t.glb",
        "body": "F",
    },
    "avaturn": {
        "url": "https://raw.githubusercontent.com/met4citizen/TalkingHead/main/avatars/avaturn.glb",
        "body": "F",
    },
    "avatar": {
        "url": "https://raw.githubusercontent.com/met4citizen/TalkingHead/main/avatars/avatar.glb",
        "body": "F",
    },
    "avatarsdk": {
        "url": "https://raw.githubusercontent.com/met4citizen/TalkingHead/main/avatars/avatarsdk.glb",
        "body": "F",
    },
}
DEFAULT_HEADTTS_DICTIONARY_URL = (
    "https://cdn.jsdelivr.net/npm/@met4citizen/headtts@1.2/dictionaries/"
)


def get_static_version() -> str:
    files = [
        BASE / "frontend" / "static" / "css" / "style.css",
        BASE / "frontend" / "static" / "js" / "app.js",
        BASE / "frontend" / "static" / "js" / "avatar.js",
    ]
    mtimes = [int(path.stat().st_mtime) for path in files if path.exists()]
    return str(max(mtimes, default=1))


def get_avatar_config() -> dict[str, str]:
    character = os.getenv(
        "TALKING_HEAD_CHARACTER",
        DEFAULT_TALKING_HEAD_CHARACTER,
    ).strip() or DEFAULT_TALKING_HEAD_CHARACTER
    preset = TALKING_HEAD_AVATAR_PRESETS.get(
        character.lower(),
        TALKING_HEAD_AVATAR_PRESETS[DEFAULT_TALKING_HEAD_CHARACTER],
    )
    custom_url = os.getenv("TALKING_HEAD_AVATAR_URL", "").strip()
    url = custom_url or preset["url"]

    body = os.getenv("TALKING_HEAD_BODY", preset["body"]).strip().upper() or preset["body"]
    if body not in {"M", "F"}:
        body = preset["body"]

    voice = os.getenv("HEADTTS_VOICE", "af_bella").strip() or "af_bella"
    language = os.getenv("HEADTTS_LANGUAGE", "en-us").strip() or "en-us"
    dictionary_url = (
        os.getenv("HEADTTS_DICTIONARY_URL", DEFAULT_HEADTTS_DICTIONARY_URL).strip()
        or DEFAULT_HEADTTS_DICTIONARY_URL
    )
    if dictionary_url.lower() in {"null", "none", "off", "false"}:
        dictionary_url = ""

    return {
        "character": character,
        "url": url,
        "body": body,
        "voice": voice,
        "language": language,
        "dictionary_url": dictionary_url,
    }


def get_orchestrator(app: FastAPI) -> Orchestrator:
    return cast(Orchestrator, app.state.orchestrator)


@asynccontextmanager
async def lifespan(app: FastAPI):
    orchestrator = get_orchestrator(app)
    await orchestrator.initialize()
    server_state = orchestrator.get_server_state()

    if orchestrator.local_llm_ready:
        log.info("KidsChat ready - open http://localhost:8000")
    else:
        log.warning(
            f"KidsChat started in degraded mode ({server_state['text']}) - "
            "open http://localhost:8000"
        )

    yield


def create_app() -> FastAPI:
    app = FastAPI(title="KidsChat", version="0.1.0", lifespan=lifespan)
    app.state.orchestrator = Orchestrator()
    app.mount("/static", StaticFiles(directory=BASE / "frontend" / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "request": request,
                "avatar_config": get_avatar_config(),
                "static_version": get_static_version(),
            },
        )

    # -----------------------------------------------------------------------
    # WebSocket — real-time voice + chat
    # -----------------------------------------------------------------------
    @app.websocket("/ws/chat")
    async def ws_chat(ws: WebSocket):
        orchestrator = get_orchestrator(ws.app)
        await ws.accept()
        session_id = id(ws)
        log.info(f"Client connected: {session_id}")
        await ws.send_text(json.dumps({
            "type": "server_state",
            "content": orchestrator.get_server_state(),
        }))

        try:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)

                match msg.get("type"):

                    # --- Text message from UI input ----------------------------
                    case "text":
                        user_text = msg["content"]
                        log.info(f"[{session_id}] Text: {user_text[:80]}")
                        async for event in orchestrator.handle_message(user_text, session_id):
                            await ws.send_text(json.dumps(event))

                    # --- Audio blob from microphone ---------------------------
                    case "audio":
                        import base64
                        audio_bytes = base64.b64decode(msg["data"])
                        sample_rate = msg.get("sampleRate", 16000)
                        mime_type = msg.get("mimeType", "audio/raw")
                        log.info(
                            f"[{session_id}] Audio: {len(audio_bytes)} bytes ({mime_type})"
                        )

                        try:
                            # 1) Transcribe
                            await ws.send_text(json.dumps({
                                "type": "status", "content": "Listening..."
                            }))
                            transcript = await orchestrator.transcribe(
                                audio_bytes,
                                sample_rate,
                                mime_type,
                            )
                        except Exception as e:
                            log.exception(f"Audio transcription failed for {session_id}: {e}")
                            await ws.send_text(json.dumps({
                                "type": "status",
                                "content": "I had trouble hearing that. Please try again!",
                            }))
                            continue

                        if not transcript.strip():
                            await ws.send_text(json.dumps({
                                "type": "status", "content": "I didn't catch that - try again!"
                            }))
                            continue

                        # Echo the transcript so the kid sees what was heard
                        await ws.send_text(json.dumps({
                            "type": "user_transcript", "content": transcript
                        }))

                        # 2) Process through orchestrator
                        async for event in orchestrator.handle_message(transcript, session_id):
                            await ws.send_text(json.dumps(event))

                    # --- Still image from webcam ----------------------------
                    case "vision":
                        import base64

                        try:
                            image_bytes = base64.b64decode(msg["data"])
                        except Exception:
                            await ws.send_text(json.dumps({
                                "type": "status",
                                "content": "I couldn't read that picture. Please try again!",
                            }))
                            continue

                        prompt = msg.get("content", "") or msg.get("prompt", "")
                        mime_type = msg.get("mimeType", "image/jpeg")
                        log.info(
                            f"[{session_id}] Vision: {len(image_bytes)} bytes ({mime_type})"
                        )

                        async for event in orchestrator.handle_vision_message(
                            prompt,
                            image_bytes,
                            mime_type,
                            session_id,
                        ):
                            await ws.send_text(json.dumps(event))

                    # --- Ping / keepalive -------------------------------------
                    case "ping":
                        await ws.send_text(json.dumps({"type": "pong"}))

                    case _:
                        log.warning(f"Unknown message type: {msg.get('type')}")

        except WebSocketDisconnect:
            log.info(f"Client disconnected: {session_id}")
            orchestrator.clear_session(session_id)
        except Exception as e:
            log.exception(f"WebSocket error for {session_id}: {e}")
            orchestrator.clear_session(session_id)

    return app


app = create_app()
