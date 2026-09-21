"""Turn an HTML fragment into readable plain text."""

import html
import re

_DROP = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_BREAKS = re.compile(r"</(p|div|tr|li|h[1-6]|table)>|<br\s*/?>", re.I)
_TAGS = re.compile(r"<[^>]+>")


def strip_tags(markup: str) -> str:
    text = _DROP.sub(" ", markup or "")
    text = _BREAKS.sub("\n", text)
    text = _TAGS.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract(path) -> tuple[str, str]:
    try:
        return strip_tags(path.read_text("utf-8", "replace")), ""
    except OSError as exc:
        return "", f"could not read file: {exc}"
