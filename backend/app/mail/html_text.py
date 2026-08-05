"""HTML email to readable text.

Every real message sampled from the office had an empty plain-text body — the
content is HTML only. So this isn't a nicety; nothing downstream works without
it.

Uses the standard library's HTMLParser rather than adding a dependency. Real
Outlook HTML is ugly (nested tables, empty paragraphs by the dozen, Word
conditional comments) but we only need readable text, not fidelity.
"""

import re
from html.parser import HTMLParser

# Content that should never reach the reader.
#
# Every tag here MUST have a closing tag. A void element (<meta>, <link>) would
# open a skip region that never closes, and everything after it would vanish.
# Real Outlook bodies begin with a bare <meta charset> — with `meta` in this
# set, every genuine message flattened to an empty string while tidy fixtures
# passed. Don't add void elements here.
SKIP_TAGS = {"script", "style", "title"}

# Tags that imply a line break in the output.
BLOCK_TAGS = {
    "p", "div", "br", "tr", "li", "table", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "hr",
}


class _Flattener(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth += 1
        elif tag in BLOCK_TAGS:
            self._parts.append("\n")
        elif tag == "td":
            # Table cells are how Outlook lays out forms. A tab keeps the
            # label and value on one line instead of splitting them.
            self._parts.append("\t")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def result(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str) -> str:
    """Flatten an HTML email body to text with sane whitespace."""
    if not html:
        return ""

    parser = _Flattener()
    try:
        parser.feed(html)
        parser.close()
        text = tidy_whitespace(parser.result())
    except Exception:
        text = ""

    # Safety net. If careful parsing produced nothing from input that clearly
    # had content, something about this document defeated it — an unclosed
    # skip region, say. Crude tag-stripping is much better than silently
    # dropping a customer's message.
    if not text and len(html) > 40:
        return tidy_whitespace(re.sub(r"<[^>]+>", " ", html))

    return text


def tidy_whitespace(text: str) -> str:
    """Collapse the whitespace soup that Outlook HTML flattens into."""
    if not text:
        return ""

    # Zero-width and non-breaking characters are everywhere in Outlook mail and
    # break both matching and display.
    text = text.replace("‌", "").replace("​", "").replace("﻿", "")
    text = text.replace("\xa0", " ")

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    # Outlook emits runs of a dozen empty paragraphs; two newlines is plenty.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def best_body(body_text: str | None, body_html: str | None) -> str:
    """Pick whichever body actually has content.

    Prefers real plain text when it exists, because it needs no guessing.
    Falls back to the flattened HTML, which in practice is the usual case.
    """
    plain = (body_text or "").strip()
    if plain:
        return tidy_whitespace(plain)
    return html_to_text(body_html or "")
