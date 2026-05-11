"""Render the scan results into a single self-contained HTML file."""

from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime
import markdown as md
from jinja2 import Environment, FileSystemLoader, select_autoescape


def render(context: dict, *, template_dir: Path, output_path: Path) -> Path:
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "htm"]),
    )
    template = env.get_template("dashboard.html.j2")
    html = template.render(**context)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def md_to_html(text: str) -> str:
    if not text:
        return ""
    return md.markdown(text, extensions=["extra", "sane_lists"])
