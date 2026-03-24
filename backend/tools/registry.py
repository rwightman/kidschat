"""
Tool registry — defines tools the local LLM can call,
provides schemas in Ollama's expected format, and dispatches execution.
"""

import logging
from typing import Any, Callable, Awaitable

from backend.tools.search import search_images
from backend.tools.diagram import create_diagram
from backend.tools.picture import draw_picture
from backend.tools.sound import play_sound
from backend.tools.fun import tell_joke, fun_fact, do_math, get_weather

log = logging.getLogger("kidschat.tools")

# Type alias for async tool functions
ToolFunc = Callable[[dict], Awaitable[dict]]


# Ollama tool schema format (OpenAI-compatible function calling)
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_images",
            "description": (
                "Search for images to show the child. Use when they ask to "
                "see something, e.g. 'show me a picture of a red panda'. "
                "Use this instead of writing Markdown image tags or raw image URLs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for (kid-safe terms only)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_diagram",
            "description": (
                "Create a chart or diagram when the child explicitly asks for one. "
                "Uses Mermaid syntax. Good for: flowcharts, life cycles, timelines, "
                "family trees, Venn diagrams, and process maps. Do not use this for "
                "ordinary explanation questions that should just be answered in text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title for the diagram",
                    },
                    "description": {
                        "type": "string",
                        "description": (
                            "What to draw — describe the relationships or steps. "
                            "The system will generate the Mermaid code."
                        ),
                    },
                },
                "required": ["title", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draw_picture",
            "description": (
                "Draw a simple picture as SVG. Use for animals, objects, scenes, "
                "or when the child explicitly asks you to draw something."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "What picture to draw, e.g. 'a happy cow'",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional extra details about the scene or style",
                    },
                },
                "required": ["subject"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_sound",
            "description": (
                "Find and play a fun sound clip in the chat. Use for animal sounds, "
                "funny noises, and when the child asks what something sounds like."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What sound to find, e.g. 'cow moo' or 'bird chirp'",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "do_math",
            "description": (
                "Calculate a math expression and show the work. "
                "Use for arithmetic, unit conversions, or word problems."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The math expression to evaluate, e.g. '(15 * 3) + 7'",
                    },
                    "explain": {
                        "type": "boolean",
                        "description": "Whether to show step-by-step work (default true)",
                    },
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name, e.g. 'Vancouver' or 'Tokyo'",
                    },
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tell_joke",
            "description": "Tell a kid-friendly joke or riddle.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Optional topic for the joke (animals, school, food, etc.)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fun_fact",
            "description": "Share an interesting, surprising fact about a topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "What topic to share a fact about",
                    },
                },
                "required": ["topic"],
            },
        },
    },
]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolFunc] = {}

    def register_defaults(self):
        """Register all built-in tools."""
        self._tools = {
            "search_images": search_images,
            "create_diagram": create_diagram,
            "draw_diagram": create_diagram,
            "draw_picture": draw_picture,
            "play_sound": play_sound,
            "do_math": do_math,
            "get_weather": get_weather,
            "tell_joke": tell_joke,
            "fun_fact": fun_fact,
        }
        log.info(f"Registered {len(self._tools)} tools: {list(self._tools.keys())}")

    def get_tool_schemas(self) -> list[dict]:
        """Return tool schemas in Ollama/OpenAI format."""
        return TOOL_SCHEMAS

    async def execute(self, name: str, args: dict) -> dict:
        """
        Execute a tool by name with the given arguments.

        Returns a dict with tool-specific results:
          - {"text": "..."} for text results
          - {"images": [...]} for image results
          - {"mermaid": "..."} for diagram results
        """
        func = self._tools.get(name)
        if not func:
            log.warning(f"Unknown tool: {name}")
            return {"text": f"I don't know how to use '{name}' yet!"}

        try:
            return await func(args)
        except Exception as e:
            log.error(f"Tool '{name}' failed: {e}")
            return {"text": f"Oops! I had trouble with that. Let me try to answer without it."}
