"""
Local LLM service — talks to Ollama.

Handles tool-calling via the Ollama chat API's native tool support and applies
small model-family specific adaptations where needed.
"""

import json
import logging
import os
import re
from typing import Optional

import ollama

log = logging.getLogger("kidschat.llm_local")

DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
DEFAULT_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
GEMMA4_THOUGHT_START_RE = re.compile(r"^\s*<\|?channel\|?>thought\s*", re.IGNORECASE)
GEMMA4_THOUGHT_CLOSE_RE = re.compile(r"<\|?channel\|?>", re.IGNORECASE)


class LocalLLM:
    def __init__(
        self,
        *,
        model: str | None = None,
        host: str | None = None,
        client=None,
    ):
        self.model = model or DEFAULT_MODEL
        self.host = host or DEFAULT_OLLAMA_HOST
        self.client = client or ollama.AsyncClient(host=self.host)

    async def check_health(self):
        """Verify Ollama is running and the model is available."""
        try:
            models = await self.client.list()
            names = [m.model for m in models.models]
            if not any(self.model in n for n in names):
                log.warning(
                    f"Model '{self.model}' not found in Ollama. "
                    f"Available: {names}. Run: ollama pull {self.model}"
                )
                return False
            else:
                log.info(f"Ollama OK - model '{self.model}' available")
                return True
        except Exception as e:
            log.error(f"Cannot reach Ollama at {self.host}: {e}")
            log.error("Start Ollama with: ollama serve")
            return False

    async def chat(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        reasoning_effort: str = "low",
    ) -> dict:
        """
        Send a chat request to the local model.

        Returns dict with:
          - "content": str (text response)
          - "tool_calls": list[dict] | None (if model invoked tools)

        The reasoning_effort param is adapted into lightweight model-family
        specific instructions; it does not rely on Ollama-only native settings.
        """
        full_system = self._build_system_prompt(system, reasoning_effort)

        ollama_messages = [{"role": "system", "content": full_system}] + messages

        try:
            kwargs = {
                "model": self.model,
                "messages": ollama_messages,
            }
            if tools:
                kwargs["tools"] = tools
            options = self._chat_options()
            if options:
                kwargs["options"] = options

            response = await self.client.chat(**kwargs)

            result = {
                "content": self._clean_model_output(response.message.content or ""),
                "tool_calls": None,
            }

            # Extract tool calls if present
            if response.message.tool_calls:
                result["tool_calls"] = [
                    {
                        "function": {
                            "name": tc.function.name,
                            "arguments": (
                                tc.function.arguments
                                if isinstance(tc.function.arguments, dict)
                                else json.loads(tc.function.arguments)
                            ),
                        }
                    }
                    for tc in response.message.tool_calls
                ]

            return result

        except Exception as e:
            log.error(f"Local LLM error: {e}")
            return {
                "content": "[ESCALATE] Local model encountered an error.",
                "tool_calls": None,
            }

    def _model_family(self) -> str:
        model_name = self.model.lower()
        if "gpt-oss" in model_name:
            return "gpt-oss"
        if "gemma4" in model_name or "gemma-4" in model_name:
            return "gemma4"
        return "generic"

    def _build_system_prompt(self, system: str, reasoning_effort: str) -> str:
        family = self._model_family()

        generic_effort_instruction = {
            "low": "\n\nBe fast and concise.",
            "medium": "\n\nThink carefully before answering, then give a concise final answer.",
            "high": "\n\nThink very carefully before answering, then give a concise final answer.",
        }
        gpt_oss_effort_instruction = {
            "low": "\n\nUse low reasoning effort. Be fast and concise.",
            "medium": "\n\nUse medium reasoning effort. Think step by step.",
            "high": "\n\nUse high reasoning effort. Think very carefully.",
        }

        if family == "gpt-oss":
            return system + gpt_oss_effort_instruction.get(reasoning_effort, "")
        if family == "gemma4":
            return (
                system
                + generic_effort_instruction.get(reasoning_effort, "")
                + "\n\nReply with only the final answer. Do not include thought-channel tags."
            )
        return system + generic_effort_instruction.get(reasoning_effort, "")

    def _chat_options(self) -> dict | None:
        if self._model_family() == "gemma4":
            # Official Ollama guidance for Gemma 4 recommends these defaults.
            return {
                "temperature": 1.0,
                "top_p": 0.95,
                "top_k": 64,
            }
        return None

    def _clean_model_output(self, text: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            return ""

        if self._model_family() == "gemma4":
            cleaned = self._strip_gemma4_thought_wrappers(cleaned)

        return cleaned.strip()

    def _strip_gemma4_thought_wrappers(self, text: str) -> str:
        """Remove Gemma 4 thought-channel wrapper text from the visible answer."""
        start_match = GEMMA4_THOUGHT_START_RE.match(text)
        if not start_match:
            return text

        match = GEMMA4_THOUGHT_CLOSE_RE.search(text, pos=start_match.end())
        if match:
            answer = text[match.end() :].strip()
            if answer:
                return answer

        text = GEMMA4_THOUGHT_START_RE.sub("", text, count=1)
        text = GEMMA4_THOUGHT_CLOSE_RE.sub("", text)
        return text.strip()
