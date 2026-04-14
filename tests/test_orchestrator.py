from __future__ import annotations

import asyncio

import pytest

from tests.support import install_dependency_stubs

install_dependency_stubs()

from backend.orchestrator import Orchestrator


class FakeLocalLLM:
    def __init__(self, responses, *, vision_support=True):
        self._responses = list(responses)
        self.calls = []
        self.vision_support = vision_support

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("No fake local LLM response available")
        return self._responses.pop(0)

    def supports_vision(self):
        return self.vision_support


class FakeCloudLLM:
    def __init__(self, response_text: str, providers=None):
        self.response_text = response_text
        self.providers = providers or ["demo"]
        self.calls = []

    def pick_provider(self) -> str:
        return self.providers[0]

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.response_text


class FakeTools:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def get_tool_schemas(self):
        return [{"type": "function", "function": {"name": "do_math"}}]

    async def execute(self, name, args):
        self.calls.append((name, args))
        return self.result


class SilentTTS:
    async def synthesize(self, text):
        return None


class RecordingTTS:
    def __init__(self):
        self.calls = []

    async def synthesize(self, text):
        self.calls.append(text)
        return None


class FakeSpeechNormalizer:
    def __init__(self, prefix="normalized: "):
        self.prefix = prefix
        self.calls = []

    def normalize(self, text):
        self.calls.append(text)
        return f"{self.prefix}{text}"


class NullSpeechPhonemizer:
    def __init__(self):
        self.calls = []

    def phonemize(self, text):
        self.calls.append(text)
        return None


class FakeSpeechPhonemizer:
    def __init__(self, prefix="phonetic: "):
        self.prefix = prefix
        self.calls = []

    def phonemize(self, text):
        self.calls.append(text)
        return f"{self.prefix}{text}"


async def _collect_events(orchestrator, message: str, session_id: int):
    return [event async for event in orchestrator.handle_message(message, session_id)]


async def _collect_vision_events(
    orchestrator,
    message: str,
    image_bytes: bytes,
    mime_type: str,
    session_id: int,
):
    return [
        event
        async for event in orchestrator.handle_vision_message(
            message,
            image_bytes,
            mime_type,
            session_id,
        )
    ]


@pytest.fixture
def fresh_orchestrator():
    orchestrator = Orchestrator()
    orchestrator.speech_phonemizer = NullSpeechPhonemizer()
    return orchestrator


def test_tool_results_are_passed_to_followup_prompt(fresh_orchestrator):
    fresh_orchestrator.local_llm_ready = True
    fresh_orchestrator.local_llm = FakeLocalLLM(
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "do_math",
                            "arguments": {"expression": "2+2"},
                        }
                    }
                ],
            },
            {"content": "It equals 4.", "tool_calls": None},
        ]
    )
    fresh_orchestrator.tools = FakeTools({"text": "Let me work that out:\n2+2 = **4**"})
    fresh_orchestrator.tts = SilentTTS()

    events = asyncio.run(_collect_events(fresh_orchestrator, "What is 2+2?", 101))

    assert [event["content"] for event in events if event["type"] == "text"] == [
        "It equals 4."
    ]
    assert "Putting that together..." in [
        event["content"] for event in events if event["type"] == "status"
    ]

    followup_messages = fresh_orchestrator.local_llm.calls[1]["messages"]
    assert "2+2 = **4**" in followup_messages[-1]["content"]
    assert '"expression": "2+2"' in followup_messages[-1]["content"]


def test_cloud_fallback_is_used_when_local_model_is_unavailable(fresh_orchestrator):
    fresh_orchestrator.local_llm_ready = False
    fresh_orchestrator.cloud_llm = FakeCloudLLM("Cloud answer here.")
    fresh_orchestrator.tts = SilentTTS()

    events = asyncio.run(_collect_events(fresh_orchestrator, "Hello", 202))

    assert [event["content"] for event in events if event["type"] == "source"] == [
        "cloud:demo"
    ]
    assert [event["content"] for event in events if event["type"] == "text"] == [
        "Cloud answer here."
    ]


def test_server_state_reflects_degraded_mode(fresh_orchestrator):
    fresh_orchestrator.local_llm_ready = False
    fresh_orchestrator.cloud_llm.providers = ["demo"]

    assert fresh_orchestrator.get_server_state() == {
        "state": "connected",
        "text": "Cloud fallback mode",
    }


def test_markdown_images_in_model_text_become_image_events(fresh_orchestrator):
    fresh_orchestrator.local_llm_ready = True
    fresh_orchestrator.local_llm = FakeLocalLLM(
        [
            {
                "content": (
                    "Here is a rhinoceros for you!\n"
                    "![Rhinoceros](https://example.com/rhino.jpg)"
                ),
                "tool_calls": None,
            }
        ]
    )
    fresh_orchestrator.tts = SilentTTS()

    events = asyncio.run(_collect_events(fresh_orchestrator, "Show me a rhino", 303))

    assert [event["content"] for event in events if event["type"] == "text"] == [
        "Here is a rhinoceros for you!"
    ]
    assert [event["content"] for event in events if event["type"] == "image"] == [
        {"url": "https://example.com/rhino.jpg", "alt": "Rhinoceros"}
    ]


def test_placeholder_image_markup_is_removed_from_visible_text(fresh_orchestrator):
    cleaned, images = fresh_orchestrator._extract_markdown_images(
        "Here’s a picture of a red panda (the one on the card):\n\n"
        "![placeholder image] (the system will show it)\n\n"
        "Red pandas climb trees."
    )

    assert cleaned == "Red pandas climb trees."
    assert images == []


def test_svg_code_blocks_become_svg_events(fresh_orchestrator):
    fresh_orchestrator.local_llm_ready = True
    fresh_orchestrator.local_llm = FakeLocalLLM(
        [
            {
                "content": (
                    "Here is a cow for you.\n\n"
                    "```svg\n"
                    "<svg viewBox=\"0 0 20 20\" xmlns=\"http://www.w3.org/2000/svg\">"
                    "<circle cx=\"10\" cy=\"10\" r=\"8\" fill=\"pink\"/>"
                    "</svg>\n"
                    "```"
                ),
                "tool_calls": None,
            }
        ]
    )
    fresh_orchestrator.tts = SilentTTS()

    events = asyncio.run(_collect_events(fresh_orchestrator, "Draw a cow", 404))

    assert [event["content"] for event in events if event["type"] == "text"] == [
        "Here is a cow for you."
    ]
    svg_events = [event["content"] for event in events if event["type"] == "svg"]
    assert len(svg_events) == 1
    assert "<svg" in svg_events[0]["svg"]
    assert svg_events[0]["title"] == "Picture"


def test_sound_tool_results_become_sound_events_and_fallback_text(fresh_orchestrator):
    fresh_orchestrator.local_llm_ready = True
    fresh_orchestrator.local_llm = FakeLocalLLM(
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "play_sound",
                            "arguments": {"query": "cow moo"},
                        }
                    }
                ],
            },
            {"content": "", "tool_calls": None},
        ]
    )
    fresh_orchestrator.tools = FakeTools(
        {
            "sounds": [
                {"url": "https://cdn.example.org/cow.mp3", "title": "Cow moo"}
            ]
        }
    )
    fresh_orchestrator.tts = SilentTTS()

    events = asyncio.run(_collect_events(fresh_orchestrator, "Play a cow sound", 505))

    assert [event["content"] for event in events if event["type"] == "sound"] == [
        {"url": "https://cdn.example.org/cow.mp3", "title": "Cow moo"}
    ]
    assert [event["content"] for event in events if event["type"] == "text"] == [
        "Here is a sound for you."
    ]

    followup_messages = fresh_orchestrator.local_llm.calls[1]["messages"]
    assert "Found a sound clip to play in the app" in followup_messages[-1]["content"]
    assert "Cow moo" in followup_messages[-1]["content"]


def test_general_explanation_questions_do_not_offer_diagram_tool(fresh_orchestrator):
    fresh_orchestrator.local_llm_ready = True
    fresh_orchestrator.local_llm = FakeLocalLLM(
        [{"content": "Rainbows appear when sunlight bends through raindrops.", "tool_calls": None}]
    )
    fresh_orchestrator.tts = SilentTTS()

    asyncio.run(_collect_events(fresh_orchestrator, "How does a rainbow form?", 606))

    tool_names = [
        tool["function"]["name"]
        for tool in fresh_orchestrator.local_llm.calls[0]["tools"]
    ]
    assert "create_diagram" not in tool_names
    assert "search_images" in tool_names


def test_explicit_diagram_requests_offer_diagram_tool(fresh_orchestrator):
    fresh_orchestrator.local_llm_ready = True
    fresh_orchestrator.local_llm = FakeLocalLLM(
        [{"content": "Here is a flowchart.", "tool_calls": None}]
    )
    fresh_orchestrator.tts = SilentTTS()

    asyncio.run(
        _collect_events(fresh_orchestrator, "Make a flowchart of the water cycle", 707)
    )

    tool_names = [
        tool["function"]["name"]
        for tool in fresh_orchestrator.local_llm.calls[0]["tools"]
    ]
    assert "create_diagram" in tool_names


def test_tts_uses_cleaned_speech_text_instead_of_display_text(fresh_orchestrator):
    fresh_orchestrator.local_llm_ready = True
    fresh_orchestrator.local_llm = FakeLocalLLM(
        [
            {
                "content": "Here’s a little cat meowing sound for you 😺 just click the play button to hear it!",
                "tool_calls": None,
            }
        ]
    )
    fresh_orchestrator.tts = RecordingTTS()
    fresh_orchestrator.speech_normalizer = FakeSpeechNormalizer()

    events = asyncio.run(_collect_events(fresh_orchestrator, "What does a cat sound like?", 808))

    assert [event["content"] for event in events if event["type"] == "speech"] == [
        {
            "speechText": "normalized: Here’s a little cat meowing sound for you",
            "displayText": "Here’s a little cat meowing sound for you 😺 just click the play button to hear it!",
            "inputType": "speech",
            "phoneticText": None,
        }
    ]
    assert [event["content"] for event in events if event["type"] == "text"] == [
        "Here’s a little cat meowing sound for you 😺 just click the play button to hear it!"
    ]
    assert fresh_orchestrator.tts.calls == ["normalized: Here’s a little cat meowing sound for you"]
    assert fresh_orchestrator.speech_normalizer.calls == [
        "Here’s a little cat meowing sound for you"
    ]


def test_speech_text_cleans_markdown_before_avatar_and_tts(fresh_orchestrator):
    fresh_orchestrator.local_llm_ready = True
    fresh_orchestrator.local_llm = FakeLocalLLM(
        [
            {
                "content": "**Cool fact!** A _rainbow_ can appear when sunlight bends through raindrops.",
                "tool_calls": None,
            }
        ]
    )
    fresh_orchestrator.tts = RecordingTTS()
    fresh_orchestrator.speech_normalizer = FakeSpeechNormalizer()

    events = asyncio.run(_collect_events(fresh_orchestrator, "Give me a fact", 909))

    assert [event["content"] for event in events if event["type"] == "speech"] == [
        {
            "speechText": "normalized: Cool fact! A rainbow can appear when sunlight bends through raindrops.",
            "displayText": "**Cool fact!** A _rainbow_ can appear when sunlight bends through raindrops.",
            "inputType": "speech",
            "phoneticText": None,
        }
    ]
    assert fresh_orchestrator.tts.calls == [
        "normalized: Cool fact! A rainbow can appear when sunlight bends through raindrops."
    ]
    assert fresh_orchestrator.speech_normalizer.calls == [
        "Cool fact! A rainbow can appear when sunlight bends through raindrops."
    ]


def test_speech_event_can_include_server_side_phonetic_text(fresh_orchestrator):
    fresh_orchestrator.local_llm_ready = True
    fresh_orchestrator.local_llm = FakeLocalLLM(
        [
            {
                "content": "The wind is strong today.",
                "tool_calls": None,
            }
        ]
    )
    fresh_orchestrator.tts = RecordingTTS()
    fresh_orchestrator.speech_normalizer = FakeSpeechNormalizer(prefix="")
    fresh_orchestrator.speech_phonemizer = FakeSpeechPhonemizer(prefix="ðə wˈɪnd | ")

    events = asyncio.run(_collect_events(fresh_orchestrator, "Tell me the weather", 910))

    assert [event["content"] for event in events if event["type"] == "speech"] == [
        {
            "speechText": "The wind is strong today.",
            "displayText": "The wind is strong today.",
            "inputType": "phonetic",
            "phoneticText": "ðə wˈɪnd | The wind is strong today.",
        }
    ]
    assert fresh_orchestrator.speech_phonemizer.calls == ["The wind is strong today."]


def test_vision_message_uses_local_model_with_attached_image(fresh_orchestrator):
    fresh_orchestrator.local_llm_ready = True
    fresh_orchestrator.local_llm = FakeLocalLLM(
        [
            {
                "content": "I see five children, one adult, and one child wearing an orange shirt.",
                "tool_calls": None,
            }
        ]
    )
    fresh_orchestrator.tts = RecordingTTS()
    fresh_orchestrator.speech_normalizer = FakeSpeechNormalizer(prefix="")

    events = asyncio.run(
        _collect_vision_events(
            fresh_orchestrator,
            "What do you see in this picture?",
            b"fake-jpeg",
            "image/jpeg",
            1001,
        )
    )

    assert [event["content"] for event in events if event["type"] == "status"] == [
        "Looking at the picture..."
    ]
    assert [event["content"] for event in events if event["type"] == "source"] == [
        "local"
    ]
    assert [event["content"] for event in events if event["type"] == "text"] == [
        "I see five children, one adult, and one child wearing an orange shirt."
    ]
    assert fresh_orchestrator.local_llm.calls[0]["images"] == [b"fake-jpeg"]
    assert fresh_orchestrator.local_llm.calls[0]["reasoning_effort"] == "medium"
    assert "It is okay to count visible people" in fresh_orchestrator.local_llm.calls[0]["system"]
