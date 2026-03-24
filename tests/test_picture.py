from __future__ import annotations

import asyncio

from tests.support import install_dependency_stubs

install_dependency_stubs()

from backend.tools.picture import draw_picture, extract_svg_payloads, sanitize_svg
from backend.tools.registry import ToolRegistry


def test_sanitize_svg_removes_scripts_and_event_handlers():
    cleaned = sanitize_svg(
        """
        <svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg" onload="alert(1)">
          <script>alert(1)</script>
          <circle cx="10" cy="10" r="8" fill="pink" onclick="evil()" />
          <foreignObject>bad</foreignObject>
        </svg>
        """
    )

    assert cleaned is not None
    assert "<script" not in cleaned
    assert "onclick" not in cleaned
    assert "onload" not in cleaned
    assert "foreignObject" not in cleaned
    assert "<circle" in cleaned


def test_extract_svg_payloads_strips_fences_and_instructions():
    cleaned, svgs = extract_svg_payloads(
        "Here is a picture.\n"
        "Copy and paste this into HTML.\n\n"
        "```svg\n"
        "<svg viewBox=\"0 0 20 20\" xmlns=\"http://www.w3.org/2000/svg\">"
        "<rect x=\"1\" y=\"1\" width=\"18\" height=\"18\" fill=\"skyblue\"/>"
        "</svg>\n"
        "```"
    )

    assert cleaned == "Here is a picture."
    assert len(svgs) == 1
    assert "<svg" in svgs[0]


def test_tool_registry_exposes_new_picture_and_diagram_names():
    registry = ToolRegistry()
    names = [item["function"]["name"] for item in registry.get_tool_schemas()]

    assert "create_diagram" in names
    assert "draw_picture" in names
    assert "draw_diagram" not in names


def test_draw_picture_returns_svg_from_model_output(monkeypatch):
    class FakeLocalLLM:
        async def chat(self, **kwargs):
            return {
                "content": (
                    "<svg viewBox=\"0 0 20 20\" xmlns=\"http://www.w3.org/2000/svg\">"
                    "<circle cx=\"10\" cy=\"10\" r=\"8\" fill=\"pink\"/>"
                    "</svg>"
                )
            }

    monkeypatch.setattr("backend.tools.picture.LocalLLM", FakeLocalLLM)

    result = asyncio.run(draw_picture({"subject": "cow"}))

    assert result["title"] == "cow"
    assert "<svg" in result["svg"]
