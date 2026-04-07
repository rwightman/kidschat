from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tests.support import install_dependency_stubs

install_dependency_stubs()

from backend.services.llm_local import LocalLLM


class FakeClient:
    def __init__(self, response=None, models=None):
        self.response = response
        self.models = models or []
        self.chat_calls = []

    async def list(self):
        return SimpleNamespace(models=[SimpleNamespace(model=name) for name in self.models])

    async def chat(self, **kwargs):
        self.chat_calls.append(kwargs)
        if self.response is None:
            raise AssertionError("No fake response configured")
        return self.response


def _fake_response(content: str, tool_calls=None):
    return SimpleNamespace(
        message=SimpleNamespace(
            content=content,
            tool_calls=tool_calls,
        )
    )


def test_gemma4_chat_uses_recommended_options_and_strips_thought_wrappers():
    client = FakeClient(
        response=_fake_response("<|channel>thought\n<channel|>The wind is strong today.")
    )
    llm = LocalLLM(model="gemma4:31b", client=client)

    result = asyncio.run(
        llm.chat(
            system="You are helpful.",
            messages=[{"role": "user", "content": "Tell me about the weather"}],
            reasoning_effort="low",
        )
    )

    assert result == {
        "content": "The wind is strong today.",
        "tool_calls": None,
    }
    assert client.chat_calls[0]["model"] == "gemma4:31b"
    assert client.chat_calls[0]["options"] == {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 64,
    }
    assert (
        "Reply with only the final answer. Do not include thought-channel tags."
        in client.chat_calls[0]["messages"][0]["content"]
    )


def test_generic_model_does_not_get_gemma4_specific_options():
    client = FakeClient(response=_fake_response("Hello there."))
    llm = LocalLLM(model="qwen3:30b", client=client)

    result = asyncio.run(
        llm.chat(
            system="You are helpful.",
            messages=[{"role": "user", "content": "Hi"}],
        )
    )

    assert result["content"] == "Hello there."
    assert "options" not in client.chat_calls[0]


def test_tool_calls_are_preserved_after_gemma4_cleanup():
    tool_calls = [
        SimpleNamespace(
            function=SimpleNamespace(
                name="tell_joke",
                arguments={"topic": "space"},
            )
        )
    ]
    client = FakeClient(
        response=_fake_response(
            "<|channel|>thought\n<|channel|>Sure, let me use a tool.",
            tool_calls=tool_calls,
        )
    )
    llm = LocalLLM(model="gemma4:31b", client=client)

    result = asyncio.run(
        llm.chat(
            system="You are helpful.",
            messages=[{"role": "user", "content": "Tell me a joke"}],
            tools=[{"type": "function", "function": {"name": "tell_joke"}}],
        )
    )

    assert result == {
        "content": "Sure, let me use a tool.",
        "tool_calls": [
            {
                "function": {
                    "name": "tell_joke",
                    "arguments": {"topic": "space"},
                }
            }
        ],
    }


def test_health_check_matches_gemma4_aliases():
    client = FakeClient(models=["gemma4:31b-it-q4_K_M"])
    llm = LocalLLM(model="gemma4:31b", client=client)

    healthy = asyncio.run(llm.check_health())

    assert healthy is True
