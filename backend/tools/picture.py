"""
Picture tool — generates simple SVG illustrations for children.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

from backend.services.llm_local import LocalLLM

log = logging.getLogger("kidschat.tools.picture")

SVG_FENCE_RE = re.compile(
    r"```(?:svg)?\s*(?P<svg><svg\b[\s\S]*?</svg>)\s*```",
    re.IGNORECASE,
)
INLINE_SVG_RE = re.compile(r"(?P<svg><svg\b[\s\S]*?</svg>)", re.IGNORECASE)
ALLOWED_TAGS = {
    "svg",
    "g",
    "path",
    "circle",
    "ellipse",
    "rect",
    "line",
    "polyline",
    "polygon",
    "text",
    "tspan",
    "title",
    "desc",
}
ALLOWED_ATTRS = {
    "viewBox",
    "width",
    "height",
    "x",
    "y",
    "x1",
    "y1",
    "x2",
    "y2",
    "cx",
    "cy",
    "r",
    "rx",
    "ry",
    "points",
    "d",
    "fill",
    "stroke",
    "stroke-width",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-dasharray",
    "fill-opacity",
    "stroke-opacity",
    "opacity",
    "transform",
    "font-size",
    "font-family",
    "font-weight",
    "text-anchor",
    "dominant-baseline",
    "preserveAspectRatio",
    "role",
    "aria-label",
}
TEXT_TAGS = {"text", "tspan", "title", "desc"}
DEFAULT_VIEWBOX = "0 0 240 180"

PICTURE_PROMPT = """\
Draw a simple standalone SVG picture for a child.

Rules:
- Output ONLY valid SVG. No markdown fences. No explanation.
- The root element must be <svg>.
- Use a viewBox and keep the picture simple and cute.
- Use only basic SVG shapes and paths.
- Do not use scripts, foreignObject, external images, CSS, or event handlers.
- Keep text labels short if you use them at all.
- Prefer a bright, friendly style with clear shapes.

Picture subject: {subject}
Extra details: {description}
"""


async def draw_picture(args: dict) -> dict:
    """
    Generate a simple SVG picture.

    Args: {"subject": "cow", "description": "standing on grass"}
    Returns: {"svg": "<svg ...>...</svg>", "title": "cow"}
    """
    subject = (args.get("subject") or args.get("title") or "").strip()
    description = (args.get("description") or subject or "").strip()
    if not subject:
        return {"text": "I need to know what picture to draw first."}

    llm = LocalLLM()
    prompt = PICTURE_PROMPT.format(subject=subject, description=description)
    result = await llm.chat(
        system=(
            "You are an SVG picture generator. "
            "Output only safe, valid standalone SVG."
        ),
        messages=[{"role": "user", "content": prompt}],
        reasoning_effort="medium",
    )

    svg = sanitize_svg(result.get("content", ""))
    if not svg:
        return {"text": f"I had trouble drawing a picture of {subject}."}

    log.info("Generated SVG picture for %s", subject)
    return {"svg": svg, "title": subject}


def extract_svg_payloads(text: str) -> tuple[str, list[str]]:
    """Extract and sanitize SVG blocks from model text."""
    if not text:
        return "", []

    svgs: list[str] = []

    def replace(match: re.Match[str]) -> str:
        svg = sanitize_svg(match.group("svg"))
        if svg:
            svgs.append(svg)
        return ""

    cleaned = SVG_FENCE_RE.sub(replace, text)
    cleaned = INLINE_SVG_RE.sub(replace, cleaned)
    cleaned = re.sub(r"(?im)^.*copy and paste.*(?:svg|html).*$", "", cleaned)
    cleaned = re.sub(r"(?im)^.*online svg .*viewer.*$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(), svgs


def sanitize_svg(svg_text: str) -> str | None:
    """Parse and sanitize SVG so it can be rendered inline safely."""
    svg_text = _extract_svg_fragment(svg_text)
    if not svg_text:
        return None

    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError:
        return None

    if _local_name(root.tag) != "svg":
        return None

    sanitized_root = _sanitize_element(root, is_root=True)
    if sanitized_root is None or len(sanitized_root) == 0:
        return None

    sanitized_root.set("xmlns", "http://www.w3.org/2000/svg")
    sanitized_root.set("role", "img")
    if "aria-label" not in sanitized_root.attrib:
        sanitized_root.set("aria-label", "Kid-friendly drawing")
    sanitized_root.set("viewBox", sanitized_root.attrib.get("viewBox", DEFAULT_VIEWBOX))
    sanitized_root.set("width", sanitized_root.attrib.get("width", "240"))
    sanitized_root.set("height", sanitized_root.attrib.get("height", "180"))

    return ET.tostring(sanitized_root, encoding="unicode")


def _extract_svg_fragment(text: str) -> str:
    match = SVG_FENCE_RE.search(text)
    if match:
        return match.group("svg").strip()

    match = INLINE_SVG_RE.search(text)
    if match:
        return match.group("svg").strip()

    return text.strip()


def _sanitize_element(element: ET.Element, *, is_root: bool = False) -> ET.Element | None:
    tag = _local_name(element.tag)
    if tag not in ALLOWED_TAGS:
        return None

    sanitized = ET.Element(tag)

    for raw_attr, value in element.attrib.items():
        attr = _local_name(raw_attr)
        if attr not in ALLOWED_ATTRS:
            continue

        lowered = value.lower()
        if attr.startswith("on"):
            continue
        if "javascript:" in lowered or "<" in value or ">" in value:
            continue
        if "url(" in lowered and not lowered.startswith("url(#"):
            continue

        sanitized.set(attr, value)

    if is_root and "viewBox" not in sanitized.attrib:
        sanitized.set("viewBox", DEFAULT_VIEWBOX)

    if element.text and tag in TEXT_TAGS:
        sanitized.text = element.text[:200]

    for child in list(element):
        sanitized_child = _sanitize_element(child)
        if sanitized_child is not None:
            if child.tail and tag in TEXT_TAGS:
                sanitized_child.tail = child.tail[:200]
            sanitized.append(sanitized_child)

    return sanitized


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1]
