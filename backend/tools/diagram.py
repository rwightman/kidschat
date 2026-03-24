"""
Diagram tool — generates Mermaid.js diagrams for visual explanations.
The LLM describes what it wants; this tool can either pass through
LLM-generated Mermaid or use the local model to generate it.
"""

import logging
from backend.services.llm_local import LocalLLM

log = logging.getLogger("kidschat.tools.diagram")

DIAGRAM_PROMPT = """\
Generate a Mermaid.js diagram for this concept. Rules:
- Use simple, kid-friendly labels (short words).
- Use colorful styling with classDef when possible.
- Keep it to 5-10 nodes max.
- Use graph TD (top-down) or graph LR (left-right) for most things.
- For sequences, use sequenceDiagram.
- For cycles, use graph with circular connections.

Output ONLY the Mermaid code, nothing else. No markdown fences.

Concept: {title}
Details: {description}
"""


async def create_diagram(args: dict) -> dict:
    """
    Generate a Mermaid diagram.

    Args: {"title": "Water Cycle", "description": "Show evaporation, condensation, precipitation"}
    Returns: {"mermaid": "graph TD\\n  A[Ocean] -->|Evaporation| B[Clouds]\\n  ..."}
    """
    title = args.get("title", "Diagram")
    description = args.get("description", title)

    # Use the local LLM to generate the Mermaid code
    llm = LocalLLM()
    prompt = DIAGRAM_PROMPT.format(title=title, description=description)

    result = await llm.chat(
        system="You are a Mermaid.js diagram generator. Output only valid Mermaid code.",
        messages=[{"role": "user", "content": prompt}],
        reasoning_effort="medium",
    )

    mermaid_code = result.get("content", "").strip()

    # Clean up: remove any markdown fences the model might add
    if mermaid_code.startswith("```"):
        lines = mermaid_code.split("\n")
        mermaid_code = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        )

    if not mermaid_code:
        # Fallback: generate a simple placeholder
        mermaid_code = f'graph TD\n  A["{title}"] --> B["Learning more..."]'

    log.info(f"Generated diagram: {mermaid_code[:80]}")
    return {"mermaid": mermaid_code, "title": title}


async def draw_diagram(args: dict) -> dict:
    """Backward-compatible alias for the old tool name."""
    return await create_diagram(args)
