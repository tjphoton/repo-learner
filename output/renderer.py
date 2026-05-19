from __future__ import annotations

import pathlib
from typing import Union

from jinja2 import Environment, FileSystemLoader

from agent.models import AnalysisOutput

_TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"


def render_html(
    analysis: AnalysisOutput,
    output_path: Union[pathlib.Path, str, None] = None,
) -> str:
    """Render an AnalysisOutput to a self-contained HTML string.

    Args:
        analysis: Validated analysis object.
        output_path: If given, write the HTML to this path as well.

    Returns:
        The rendered HTML string.
    """
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=False,  # we trust agent output; needed for Mermaid/code blocks
    )
    template = env.get_template("report.html.j2")
    html = template.render(analysis=analysis)

    if output_path is not None:
        p = pathlib.Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")

    return html
