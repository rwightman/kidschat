"""
Local LLM service — talks to Ollama running gpt-oss:20b.
Handles tool-calling via the Ollama chat API's native tool support.
"""

import json
import logging
import os
from typing import Optional

import ollama

log = logging.getLogger("kidschat.llm_local")

MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


class LocalLLM:
    def __init__(self):
        self.client = ollama.AsyncClient(host=OLLAMA_HOST)

    async def check_health(self):
        """Verify Ollama is running and the model is available."""
        try:
            models = await self.client.list()
            names = [m.model for m in models.models]
            if not any(MODEL in n for n in names):
                log.warning(
                    f"Model '{MODEL}' not found in Ollama. "
                    f"Available: {names}. Run: ollama pull {MODEL}"
                )
                return False
            else:
                log.info(f"Ollama OK - model '{MODEL}' available")
                return True
        except Exception as e:
            log.error(f"Cannot reach Ollama at {OLLAMA_HOST}: {e}")
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

        The reasoning_effort param maps to gpt-oss's native effort levels.
        We inject it as a system-level instruction.
        """
        effort_instruction = {
            "low": "\n\nUse low reasoning effort. Be fast and concise.",
            "medium": "\n\nUse medium reasoning effort. Think step by step.",
            "high": "\n\nUse high reasoning effort. Think very carefully.",
        }

        full_system = system + effort_instruction.get(reasoning_effort, "")

        ollama_messages = [{"role": "system", "content": full_system}] + messages

        try:
            kwargs = {
                "model": MODEL,
                "messages": ollama_messages,
            }
            if tools:
                kwargs["tools"] = tools

            response = await self.client.chat(**kwargs)

            result = {"content": response.message.content or "", "tool_calls": None}

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
