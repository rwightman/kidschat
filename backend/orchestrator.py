"""
Orchestrator - the brain of KidsChat.

Manages conversation history, routes between local and cloud LLMs,
dispatches tool calls, and coordinates STT/TTS.
"""

import json
import logging
import re
from typing import AsyncGenerator

from backend.services.llm_local import LocalLLM
from backend.services.llm_cloud import CloudLLM
from backend.services.stt import SpeechToText
from backend.services.speech_normalizer import SpeechNormalizer
from backend.services.speech_phonemizer import SpeechPhonemizer
from backend.services.tts import TextToSpeech, clean_text_for_speech
from backend.tools.registry import ToolRegistry
from backend.tools.picture import extract_svg_payloads

log = logging.getLogger("kidschat.orchestrator")
MARKDOWN_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>https?://[^)\s]+)\)")
DIAGRAM_REQUEST_RE = re.compile(
    r"\b("
    r"chart|diagram|flowchart|flow chart|life cycle|cycle|timeline|"
    r"family tree|venn diagram|mind map|process map|tree diagram"
    r")\b",
    re.IGNORECASE,
)
SPEECH_UI_INSTRUCTION_RE = re.compile(
    r"(?i)(?:\s*[-,:;]?\s*)?"
    r"(?:just\s+)?(?:click|tap|press)\s+(?:the\s+)?play button"
    r"(?:\s+to\s+hear\s+(?:it|the sound))?"
    r"[.!]?"
)

# Max conversation history per session (keeps context manageable for local LLM)
MAX_HISTORY = 20

SYSTEM_PROMPT = """\
You are KidsChat, a friendly, enthusiastic AI assistant for children.

Rules:
- Use simple, clear language appropriate for kids ages 6-12.
- Be encouraging and positive. Celebrate curiosity!
- If you don't know something, say so honestly.
- Keep answers concise (2-4 sentences) unless asked for more detail.
- NEVER produce scary, violent, or inappropriate content.
- If a child seems upset, be kind and suggest they talk to a trusted adult.

You have access to tools. Use them when helpful:
- search_images: Find pictures to show the child.
- create_diagram: Create a chart or diagram to explain something.
- draw_picture: Draw a simple picture as SVG.
- play_sound: Find and play a short sound clip.
- do_math: Calculate math problems and show work.
- get_weather: Look up weather for a location.
- tell_joke: Share a kid-friendly joke or riddle.
- fun_fact: Share an interesting fact about a topic.
- If the child asks to see a picture, photo, or image of something, use search_images.
- If the child asks you to draw a simple picture or explicitly asks for SVG, use draw_picture.
- Only use create_diagram when the child explicitly asks for a chart, diagram,
  flowchart, cycle, timeline, family tree, mind map, or Venn diagram.
- Do not use create_diagram for ordinary explanation questions like
  "How does a rainbow form?" Prefer a short, kid-friendly explanation instead.
- If the child asks what something sounds like or asks you to play a sound, use play_sound.
- Never paste raw image URLs or Markdown image tags like ![alt](url).
  The app shows tool images separately.
- Never paste raw SVG or XML into your reply. The app shows SVG pictures separately.
- Never paste raw sound URLs. The app can play sound clips separately.
- Do not tell the child to click buttons or use on-screen controls.
  Mention media naturally instead.

When you need to use a tool, call it. The result will be shown to the child
alongside your explanation.

If a question is too complex for you to answer well, respond with exactly:
[ESCALATE] followed by a brief reason why.
"""


class Orchestrator:
    def __init__(self):
        self.local_llm = LocalLLM()
        self.cloud_llm = CloudLLM()
        self.stt = SpeechToText()
        self.speech_normalizer = SpeechNormalizer()
        self.speech_phonemizer = SpeechPhonemizer()
        self.tts = TextToSpeech()
        self.tools = ToolRegistry()
        self.local_llm_ready = False
        # session_id -> list of {"role": ..., "content": ...}
        self.sessions: dict[int, list[dict]] = {}

    async def initialize(self):
        """Warm up models and verify connectivity."""
        self.local_llm_ready = await self.local_llm.check_health()
        self.tools.register_defaults()
        log.info("Orchestrator initialized")

    def get_server_state(self) -> dict[str, str]:
        """Return the current server readiness state for the UI."""
        if self.local_llm_ready:
            return {"state": "connected", "text": "Ready!"}

        if self.cloud_llm.providers:
            return {
                "state": "connected",
                "text": "Cloud fallback mode",
            }

        return {
            "state": "error",
            "text": "Local model offline",
        }

    def clear_session(self, session_id: int):
        self.sessions.pop(session_id, None)

    def _get_history(self, session_id: int) -> list[dict]:
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        return self.sessions[session_id]

    # ------------------------------------------------------------------
    # Speech-to-text
    # ------------------------------------------------------------------
    async def transcribe(
        self,
        audio_bytes: bytes,
        sample_rate: int = 16000,
        mime_type: str = "audio/raw",
    ) -> str:
        return await self.stt.transcribe(audio_bytes, sample_rate, mime_type)

    # ------------------------------------------------------------------
    # Main message handler
    # ------------------------------------------------------------------
    async def handle_message(
        self, user_text: str, session_id: int
    ) -> AsyncGenerator[dict, None]:
        """
        Process a user message and yield response events:
          {"type": "status",   "content": "Thinking..."}
          {"type": "text",     "content": "Here's what I found..."}
          {"type": "image",    "content": {"url": "...", "alt": "..."}}
          {"type": "diagram",  "content": "<mermaid code>"}
          {"type": "svg",      "content": {"svg": "<svg...>", "title": "..."}}
          {"type": "sound",    "content": {"url": "...", "title": "..."}}
          {"type": "speech",   "content": {
              "speechText": "...",
              "displayText": "...",
              "inputType": "speech" | "phonetic",
              "phoneticText": "...",
          }}
          {"type": "audio",    "content": "<base64 audio>"}
          {"type": "source",   "content": "local" | "cloud:claude" | ...}
          {"type": "done"}
        """
        history = self._get_history(session_id)
        rendered_image_urls: set[str] = set()
        rendered_svgs: set[str] = set()
        history.append({"role": "user", "content": user_text})

        # Trim history to keep context window manageable
        if len(history) > MAX_HISTORY:
            history[:] = history[-MAX_HISTORY:]

        if not self.local_llm_ready:
            if self.cloud_llm.providers:
                log.info("Local model unavailable, routing directly to cloud")
                yield {"type": "status", "content": "Let me think about that..."}

                cloud_provider = self.cloud_llm.pick_provider()
                yield {"type": "source", "content": f"cloud:{cloud_provider}"}

                response_text = await self.cloud_llm.chat(
                    provider=cloud_provider,
                    system=SYSTEM_PROMPT,
                    messages=history,
                )
            else:
                response_text = (
                    "I need my local AI brain to wake up first. "
                    "Please ask a grown-up to start Ollama for me."
                )

            response_text, svg_payloads = extract_svg_payloads(response_text)
            response_text, markdown_images = self._extract_markdown_images(response_text)
            response_text = self._default_display_text(
                response_text,
                markdown_images=markdown_images,
                svg_payloads=svg_payloads,
            )
            history.append({"role": "assistant", "content": response_text})
            if response_text:
                yield {"type": "text", "content": response_text}
            for image in markdown_images:
                yield {"type": "image", "content": image}
            for svg in svg_payloads:
                yield {"type": "svg", "content": {"svg": svg, "title": "Picture"}}
            speech_text = self._speech_text_for_response(
                response_text,
                markdown_images=markdown_images,
                svg_payloads=svg_payloads,
            )
            if speech_text:
                yield self._speech_event(speech_text, response_text)
                yield await self._speak(speech_text)
            yield {"type": "done"}
            return

        # --- Step 1: Try local LLM first (fast path) ---
        yield {"type": "status", "content": "Thinking..."}
        yield {"type": "source", "content": "local"}

        local_response = await self.local_llm.chat(
            system=SYSTEM_PROMPT,
            messages=history,
            tools=self._tool_schemas_for_message(user_text),
            reasoning_effort="low",
        )

        # --- Step 2: Check if model wants to escalate ---
        if self._should_escalate(local_response):
            log.info(f"Escalating to cloud for: {user_text[:60]}")
            yield {"type": "status", "content": "Let me think harder about this..."}

            cloud_provider = self.cloud_llm.pick_provider()
            yield {"type": "source", "content": f"cloud:{cloud_provider}"}

            cloud_response = await self.cloud_llm.chat(
                provider=cloud_provider,
                system=SYSTEM_PROMPT,
                messages=history,
            )
            response_text = cloud_response
            response_text, svg_payloads = extract_svg_payloads(response_text)
            response_text, markdown_images = self._extract_markdown_images(response_text)
            response_text = self._default_display_text(
                response_text,
                markdown_images=markdown_images,
                svg_payloads=svg_payloads,
            )
            history.append({"role": "assistant", "content": response_text})

            if response_text:
                yield {"type": "text", "content": response_text}
            for image in markdown_images:
                yield {"type": "image", "content": image}
            for svg in svg_payloads:
                yield {"type": "svg", "content": {"svg": svg, "title": "Picture"}}
            speech_text = self._speech_text_for_response(
                response_text,
                markdown_images=markdown_images,
                svg_payloads=svg_payloads,
            )
            if speech_text:
                yield self._speech_event(speech_text, response_text)
                yield await self._speak(speech_text)
            yield {"type": "done"}
            return

        # --- Step 3: Handle tool calls if present ---
        tool_results: list[dict] = []
        if local_response.get("tool_calls"):
            for tool_call in local_response["tool_calls"]:
                tool_name = tool_call["function"]["name"]
                tool_args = tool_call["function"]["arguments"]
                log.info(f"Tool call: {tool_name}({tool_args})")

                yield {
                    "type": "status",
                    "content": f"Using {tool_name.replace('_', ' ')}...",
                }

                result = await self.tools.execute(tool_name, tool_args)
                tool_results.append(
                    {
                        "name": tool_name,
                        "args": tool_args,
                        "result": result,
                    }
                )

                # Yield tool results as appropriate UI events
                for event in self._tool_result_to_events(tool_name, result):
                    if event["type"] == "image":
                        rendered_image_urls.add(event["content"]["url"])
                    elif event["type"] == "svg":
                        rendered_svgs.add(event["content"]["svg"])
                    yield event

            followup_messages = history + [
                {
                    "role": "assistant",
                    "content": self._format_tool_call_summary(tool_results),
                },
                {
                    "role": "user",
                    "content": self._format_tool_results(tool_results),
                },
            ]

            yield {"type": "status", "content": "Putting that together..."}

            followup = await self.local_llm.chat(
                system=SYSTEM_PROMPT,
                messages=followup_messages,
                reasoning_effort="low",
            )

            if self._should_escalate(followup):
                log.info(f"Escalating follow-up to cloud for: {user_text[:60]}")
                yield {"type": "status", "content": "Let me think harder about this..."}

                cloud_provider = self.cloud_llm.pick_provider()
                yield {"type": "source", "content": f"cloud:{cloud_provider}"}

                response_text = await self.cloud_llm.chat(
                    provider=cloud_provider,
                    system=SYSTEM_PROMPT,
                    messages=followup_messages,
                )
            else:
                response_text = followup.get("content", "").strip()

            if not response_text:
                response_text = self._fallback_tool_response(tool_results)
        else:
            response_text = local_response.get("content", "")

        # --- Step 4: Send response ---
        response_text, svg_payloads = extract_svg_payloads(response_text)
        response_text, markdown_images = self._extract_markdown_images(response_text)
        response_text = self._default_display_text(
            response_text,
            markdown_images=markdown_images,
            svg_payloads=svg_payloads,
        )

        history.append({"role": "assistant", "content": response_text})
        if response_text:
            yield {"type": "text", "content": response_text}

        for image in markdown_images:
            if image["url"] in rendered_image_urls:
                continue
            rendered_image_urls.add(image["url"])
            yield {"type": "image", "content": image}

        for svg in svg_payloads:
            if svg in rendered_svgs:
                continue
            rendered_svgs.add(svg)
            yield {"type": "svg", "content": {"svg": svg, "title": "Picture"}}

        speech_text = self._speech_text_for_response(
            response_text,
            tool_results=tool_results,
            markdown_images=markdown_images,
            svg_payloads=svg_payloads,
        )
        if speech_text:
            yield self._speech_event(speech_text, response_text)
            yield await self._speak(speech_text)
        yield {"type": "done"}

    # ------------------------------------------------------------------
    # Tool availability
    # ------------------------------------------------------------------
    def _tool_schemas_for_message(self, user_text: str) -> list[dict]:
        """Offer diagram creation only for explicit diagram/chart requests."""
        schemas = self.tools.get_tool_schemas()
        if self._should_offer_diagram_tool(user_text):
            return schemas

        return [
            schema
            for schema in schemas
            if schema.get("function", {}).get("name") != "create_diagram"
        ]

    def _should_offer_diagram_tool(self, user_text: str) -> bool:
        """Return True only for explicit requests for chart-like visuals."""
        return bool(DIAGRAM_REQUEST_RE.search(user_text or ""))

    # ------------------------------------------------------------------
    # Escalation detection
    # ------------------------------------------------------------------
    def _should_escalate(self, response: dict) -> bool:
        """Decide whether to punt to a cloud model."""
        content = response.get("content", "")

        # Explicit escalation signal from the model
        if "[ESCALATE]" in content:
            return True

        # Heuristic: very short or uncertain responses
        uncertainty_markers = [
            "i'm not sure", "i don't know", "i'm not certain",
            "that's beyond", "i can't help with", "complex question",
        ]
        content_lower = content.lower()
        if any(marker in content_lower for marker in uncertainty_markers):
            return True

        return False

    # ------------------------------------------------------------------
    # Tool result formatting
    # ------------------------------------------------------------------
    def _tool_result_to_events(self, tool_name: str, result: dict) -> list[dict]:
        """Convert a tool execution result into WebSocket events."""
        events = []

        if tool_name == "search_images" and result.get("images"):
            for img in result["images"][:3]:
                events.append({
                    "type": "image",
                    "content": {"url": img["url"], "alt": img.get("alt", "")},
                })

        elif tool_name in {"create_diagram", "draw_diagram"} and result.get("mermaid"):
            events.append({"type": "diagram", "content": result["mermaid"]})

        elif tool_name == "draw_picture" and result.get("svg"):
            events.append(
                {
                    "type": "svg",
                    "content": {
                        "svg": result["svg"],
                        "title": result.get("title", "Picture"),
                    },
                }
            )

        elif tool_name == "play_sound" and result.get("sounds"):
            events.append(
                {
                    "type": "sound",
                    "content": result["sounds"][0],
                }
            )

        return events

    def _format_tool_call_summary(self, tool_results: list[dict]) -> str:
        """Summarize which tools were used for the follow-up turn."""
        names = ", ".join(item["name"] for item in tool_results)
        return f"Used tools: {names}"

    def _format_tool_results(self, tool_results: list[dict]) -> str:
        """Format tool results as a synthetic prompt for the follow-up turn."""
        parts = [
            (
                "Tool results for your last answer. Reply to the child directly "
                "using these results. Do not mention tool names or raw JSON. "
                "Do not include Markdown image tags or paste raw URLs."
            )
        ]

        for item in tool_results:
            parts.append(self._summarize_tool_result(item))

        return "\n\n".join(parts)

    def _summarize_tool_result(self, item: dict) -> str:
        """Summarize tool output without leaking raw URLs into the model prompt."""
        tool_name = item["name"]
        args = item["args"]
        result = item["result"]

        lines = [
            f"Tool: {tool_name}",
            f"Arguments: {json.dumps(args, sort_keys=True)}",
        ]

        if tool_name == "search_images":
            images = result.get("images", [])
            if images:
                labels = [img.get("alt", "Image") for img in images[:3]]
                lines.append(
                    "Result: "
                    f"Found {len(images)} image result(s) to show in the app. "
                    f"Subjects: {', '.join(labels)}."
                )
                lines.append(
                    "When you reply, acknowledge the pictures briefly, but do not "
                    "mention cards, placeholders, URLs, or system behavior."
                )
            elif result.get("text"):
                lines.append(f"Result: {result['text']}")
            else:
                lines.append("Result: No images were found.")
        elif tool_name == "draw_picture":
            if result.get("svg"):
                lines.append(
                    "Result: Created an SVG picture to show in the app. "
                    f"Subject: {result.get('title') or args.get('subject', 'picture')}."
                )
                lines.append(
                    "When you reply, mention the picture naturally, but do not "
                    "paste SVG, XML, or talk about app internals."
                )
            elif result.get("text"):
                lines.append(f"Result: {result['text']}")
            else:
                lines.append("Result: No picture was created.")
        elif tool_name == "play_sound":
            sounds = result.get("sounds", [])
            if sounds:
                lines.append(
                    "Result: Found a sound clip to play in the app. "
                    f"Clip title: {sounds[0].get('title', args.get('query', 'sound'))}."
                )
                lines.append(
                    "When you reply, mention the sound naturally, but do not paste "
                    "sound URLs or app internals."
                )
            elif result.get("text"):
                lines.append(f"Result: {result['text']}")
            else:
                lines.append("Result: No sound was found.")
        elif tool_name in {"create_diagram", "draw_diagram"} and result.get("mermaid"):
            lines.append(
                "Result: Created a chart or diagram to show in the app. "
                f"Title: {result.get('title') or args.get('title', 'diagram')}."
            )
            lines.append(
                "When you reply, mention the chart or diagram briefly, but do not "
                "paste Mermaid code."
            )
        else:
            lines.append(f"Result: {json.dumps(result, sort_keys=True)}")

        return "\n".join(lines)

    def _fallback_tool_response(self, tool_results: list[dict]) -> str:
        """Fallback text if the follow-up model response is empty."""
        text_results = [
            item["result"]["text"].strip()
            for item in tool_results
            if item["result"].get("text")
        ]
        if text_results:
            return "\n\n".join(text_results)

        for item in tool_results:
            if item["result"].get("images"):
                return "Here are some pictures to help explain it."
            if item["result"].get("mermaid"):
                return "Here is a diagram to help explain it."
            if item["result"].get("svg"):
                return "Here is a picture for you."
            if item["result"].get("sounds"):
                return "Here is a sound for you."

        return "Here you go!"

    def _default_display_text(
        self,
        text: str,
        *,
        markdown_images: list[dict] | None = None,
        svg_payloads: list[str] | None = None,
    ) -> str:
        """Provide a friendly fallback line when only media is present."""
        if text:
            return text
        if svg_payloads:
            return "Here is a picture for you."
        if markdown_images:
            return "Here you go!"
        return ""

    def _speech_text_for_response(
        self,
        text: str,
        *,
        tool_results: list[dict] | None = None,
        markdown_images: list[dict] | None = None,
        svg_payloads: list[str] | None = None,
    ) -> str:
        """Build a cleaner speech-only version of the visible response text."""
        speech_text = self._normalize_speech_text(
            self._strip_speech_ui_instructions(text)
        )
        if speech_text:
            return speech_text

        for item in tool_results or []:
            media_speech = self._speech_text_for_tool_result(item)
            if media_speech:
                return media_speech

        if svg_payloads:
            return "Here is a picture for you."
        if markdown_images:
            return "Here are some pictures for you."
        return ""

    def _speech_text_for_tool_result(self, item: dict) -> str:
        """Return short spoken fallback text for media-heavy tool results."""
        result = item["result"]
        tool_name = item["name"]

        if tool_name == "play_sound" and result.get("sounds"):
            return self._normalize_speech_text("Here is a sound for you.")
        if tool_name == "draw_picture" and result.get("svg"):
            return self._normalize_speech_text("Here is a picture for you.")
        if tool_name in {"create_diagram", "draw_diagram"} and result.get("mermaid"):
            return self._normalize_speech_text("Here is a diagram to help explain it.")
        if tool_name == "search_images" and result.get("images"):
            return self._normalize_speech_text("Here are some pictures for you.")
        if result.get("text"):
            return self._normalize_speech_text(
                self._strip_speech_ui_instructions(result["text"])
            )
        return ""

    def _strip_speech_ui_instructions(self, text: str) -> str:
        """Remove screen-control instructions from spoken text."""
        if not text:
            return ""

        cleaned = SPEECH_UI_INSTRUCTION_RE.sub("", text)
        cleaned = re.sub(
            r"(?i)\b(?:in|on)\s+the\s+app\b",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"(?i)\b(?:on\s+the\s+card|in\s+the\s+card|shown\s+(?:above|below))\b",
            "",
            cleaned,
        )
        cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip(" \n\t-,:;")

    def _normalize_speech_text(self, text: str) -> str:
        """Apply optional TTS-specific text normalization."""
        if not text:
            return ""
        cleaned = clean_text_for_speech(text)
        if not cleaned:
            return ""
        return self.speech_normalizer.normalize(cleaned)

    def _speech_event(self, speech_text: str, display_text: str) -> dict:
        """Package a speech-only event for client-side TTS/lip-sync consumers."""
        phonetic_text = self.speech_phonemizer.phonemize(speech_text)
        return {
            "type": "speech",
            "content": {
                "speechText": speech_text,
                "displayText": display_text,
                "inputType": "phonetic" if phonetic_text else "speech",
                "phoneticText": phonetic_text,
            },
        }

    def _extract_markdown_images(self, text: str) -> tuple[str, list[dict]]:
        """Strip Markdown image tags from model text and convert them to UI images."""
        if not text:
            return "", []

        images: list[dict] = []

        def replace(match: re.Match[str]) -> str:
            url = match.group("url").strip()
            if not url.startswith(("http://", "https://")):
                return ""

            alt = match.group("alt").strip() or "Image"
            images.append({"url": url, "alt": alt})
            return ""

        cleaned = MARKDOWN_IMAGE_RE.sub(replace, text)
        cleaned = re.sub(r"(?im)^\s*!\[[^\]]*\]\s*(?:\([^)]*\))?\s*$", "", cleaned)
        cleaned = re.sub(
            r"(?im)^\s*(?:here(?:['’]s| is)\s+)?(?:a\s+)?(?:picture|photo|image)[^\n]*(?:card|system will show it)[^\n]*[:.]?\s*$",
            "",
            cleaned,
        )
        cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip(), images

    # ------------------------------------------------------------------
    # TTS
    # ------------------------------------------------------------------
    async def _speak(self, text: str) -> dict:
        """Generate TTS audio and return as a WebSocket event."""
        try:
            audio_b64 = await self.tts.synthesize(text)
            if audio_b64:
                return {"type": "audio", "content": audio_b64}
        except Exception as e:
            log.warning(f"TTS failed: {e}")
        return {"type": "audio", "content": None}
