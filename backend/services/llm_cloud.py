"""
Cloud LLM service — escalation to Claude, OpenAI, or Gemini
when the local model can't handle a query.

Uses a round-robin provider selection with fallback.
"""

import logging
import os
from itertools import cycle
from typing import Optional

log = logging.getLogger("kidschat.llm_cloud")


class CloudLLM:
    def __init__(self):
        self.providers: list[str] = []
        self._provider_cycle = None

        # Detect which providers have API keys configured
        if os.getenv("ANTHROPIC_API_KEY"):
            self.providers.append("claude")
        if os.getenv("OPENAI_API_KEY"):
            self.providers.append("openai")
        if os.getenv("GOOGLE_API_KEY"):
            self.providers.append("gemini")

        if self.providers:
            self._provider_cycle = cycle(self.providers)
            log.info(f"Cloud providers available: {self.providers}")
        else:
            log.warning(
                "No cloud API keys configured — escalation will fall back to "
                "local model with high reasoning effort"
            )

    def pick_provider(self) -> str:
        """Round-robin provider selection."""
        if self._provider_cycle:
            return next(self._provider_cycle)
        return "local_fallback"

    async def chat(
        self,
        provider: str,
        system: str,
        messages: list[dict],
    ) -> str:
        """
        Send the conversation to a cloud provider and return the response text.
        Falls back through providers if one fails.
        """
        tried = set()

        while len(tried) < len(self.providers) + 1:
            tried.add(provider)
            try:
                match provider:
                    case "claude":
                        return await self._call_claude(system, messages)
                    case "openai":
                        return await self._call_openai(system, messages)
                    case "gemini":
                        return await self._call_gemini(system, messages)
                    case _:
                        return await self._local_high_effort(system, messages)
            except Exception as e:
                log.warning(f"Cloud provider '{provider}' failed: {e}")
                # Try next provider
                provider = self.pick_provider()
                if provider in tried:
                    break

        return "Hmm, I'm having trouble thinking right now. Can you ask me again?"

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    async def _call_claude(self, system: str, messages: list[dict]) -> str:
        import anthropic

        client = anthropic.AsyncAnthropic()

        # Filter to user/assistant messages only (Claude API format)
        api_messages = [
            m for m in messages if m["role"] in ("user", "assistant")
        ]

        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system,
            messages=api_messages,
        )
        return response.content[0].text

    async def _call_openai(self, system: str, messages: list[dict]) -> str:
        from openai import AsyncOpenAI

        client = AsyncOpenAI()

        api_messages = [{"role": "system", "content": system}] + [
            m for m in messages if m["role"] in ("user", "assistant")
        ]

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=api_messages,
            max_tokens=1024,
        )
        return response.choices[0].message.content

    async def _call_gemini(self, system: str, messages: list[dict]) -> str:
        from google import genai

        client = genai.Client()

        # Build Gemini conversation format
        contents = []
        for m in messages:
            if m["role"] == "user":
                contents.append({"role": "user", "parts": [{"text": m["content"]}]})
            elif m["role"] == "assistant":
                contents.append({"role": "model", "parts": [{"text": m["content"]}]})

        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=contents,
            config={
                "system_instruction": system,
                "max_output_tokens": 1024,
            },
        )
        return response.text

    async def _local_high_effort(self, system: str, messages: list[dict]) -> str:
        """Fallback: re-run local model with high reasoning effort."""
        from backend.services.llm_local import LocalLLM

        local = LocalLLM()
        result = await local.chat(
            system=system, messages=messages, reasoning_effort="high"
        )
        return result.get("content", "I'm not sure about that one!")
