from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.app import create_app


async def _fake_initialize():
    return None


def test_index_route_renders(monkeypatch):
    app = create_app()
    monkeypatch.setattr(app.state.orchestrator, "initialize", _fake_initialize)

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "KidsChat" in response.text


def test_audio_websocket_message_is_transcribed_and_processed(monkeypatch):
    app = create_app()
    monkeypatch.setattr(app.state.orchestrator, "initialize", _fake_initialize)

    async def _fake_transcribe(audio_bytes, sample_rate, mime_type):
        assert audio_bytes == b"RIFFfake"
        assert sample_rate == 16000
        assert mime_type == "audio/wav"
        return "Hello from the microphone"

    async def _fake_handle_message(user_text, session_id):
        assert user_text == "Hello from the microphone"
        yield {"type": "text", "content": "I heard you loud and clear."}
        yield {"type": "done"}

    monkeypatch.setattr(app.state.orchestrator, "transcribe", _fake_transcribe)
    monkeypatch.setattr(app.state.orchestrator, "handle_message", _fake_handle_message)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat") as ws:
            server_state = json.loads(ws.receive_text())
            assert server_state["type"] == "server_state"

            ws.send_text(json.dumps({
                "type": "audio",
                "data": "UklGRmZha2U=",
                "sampleRate": 16000,
                "mimeType": "audio/wav",
            }))

            events = [json.loads(ws.receive_text()) for _ in range(4)]

    assert [event["type"] for event in events] == [
        "status",
        "user_transcript",
        "text",
        "done",
    ]
    assert events[0]["content"] == "Listening..."
    assert events[1]["content"] == "Hello from the microphone"
