"""Trusted presentation config shared with the web app, never actor-supplied."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from rich.console import Group
from rich.style import Style
from rich.text import Span, Text

COLOR_KEYS = {"background", "foreground", "surface", "muted", "mutedForeground", "primary", "primaryForeground", "border"}


def load_brand():
    path = Path(os.environ.get("GENESIS_BRAND_CONFIG", Path(__file__).resolve().parents[2] / "branding/site.json"))
    brand = json.loads(path.read_text(encoding="utf-8"))
    fields = {"version", "name", "company", "title", "description", "website", "docs", "support", "light", "dark"}
    if set(brand) != fields:
        raise ValueError("Invalid branding fields")
    for key in fields - {"light", "dark"}:
        value = brand[key]
        if not isinstance(value, str) or not 1 <= len(value) <= 120 or re.search(r"[<>\x00-\x1f]", value):
            raise ValueError("Invalid branding text")
    for key in ["website", "docs"]:
        from urllib.parse import urlparse

        url = urlparse(brand[key])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Invalid branding URL")
    if not re.fullmatch(r"mailto:[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+", brand["support"]):
        raise ValueError("Invalid support URL")
    for key in ["light", "dark"]:
        if not isinstance(brand[key], dict) or set(brand[key]) != COLOR_KEYS or any(not isinstance(v, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", v) for v in brand[key].values()):
            raise ValueError("Invalid brand palette")
    return brand


def brand_header(brand, model, thread):
    palette = brand["dark"]
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(f" {brand['name']} ", style=f"bold {palette['primaryForeground']} on {palette['primary']}")
    text.append(f"  {model or 'default'}  ·  {thread}", style=palette["foreground"])
    return text


def brand_rendered_text(text, brand):
    """Map upstream render colors locally; preserve user content and Rich flags."""
    if isinstance(text, Group):
        return Group(*(brand_rendered_text(item, brand) for item in text.renderables))
    if not isinstance(text, Text):
        return text
    from deerflow.tui.theme import THEME

    p = brand["dark"]
    mapping = {
        THEME.bg: p["background"],
        THEME.panel: p["surface"],
        THEME.text: p["foreground"],
        THEME.dim: p["mutedForeground"],
        THEME.muted: p["mutedForeground"],
        THEME.primary: p["primary"],
        THEME.user: p["primary"],
        THEME.assistant: p["foreground"],
    }
    result = text.copy()
    spans = []
    for span in text.spans:
        style = Style.parse(span.style) if isinstance(span.style, str) else span.style
        color = style.color.get_truecolor().hex if style.color else None
        bg = style.bgcolor.get_truecolor().hex if style.bgcolor else None
        mapped = style + Style(color=mapping.get(color), bgcolor=mapping.get(bg))
        spans.append(Span(span.start, span.end, mapped))
    result.spans = spans
    return result
