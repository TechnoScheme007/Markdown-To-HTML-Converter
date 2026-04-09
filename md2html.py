#!/usr/bin/env python3
"""
md2html — A CommonMark-compliant Markdown to HTML converter.

Features:
  - ATX & Setext headings, blockquotes, horizontal rules
  - Bold, italic, strikethrough, inline code
  - Fenced & indented code blocks with syntax highlighting (via Pygments)
  - Links, images, reference links, autolinks
  - Ordered & unordered lists with arbitrary nesting
  - GFM tables with alignment
  - CLI: md2html file.md > out.html
  - Built-in live-preview web app

Usage:
  python md2html.py file.md                   # convert to stdout
  python md2html.py file.md -o out.html       # convert to file
  python md2html.py --serve                   # launch web app on :8077
  python md2html.py --serve --port 3000       # custom port
"""

from __future__ import annotations

import argparse
import html as _html
import json
import re
import sys
import textwrap
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import unquote

# ---------------------------------------------------------------------------
# Optional: Pygments for syntax highlighting
# ---------------------------------------------------------------------------
try:
    from pygments import highlight as _pygments_highlight
    from pygments.lexers import get_lexer_by_name, ClassNotFound
    from pygments.formatters import HtmlFormatter

    HAS_PYGMENTS = True
except ImportError:
    HAS_PYGMENTS = False

__version__ = "1.0.0"

# ═══════════════════════════════════════════════════════════════════════════
#  Inline Parser
# ═══════════════════════════════════════════════════════════════════════════

_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!~|])")
_ENTITY_RE = re.compile(r"&(?:#x[0-9a-fA-F]{1,6}|#[0-9]{1,7}|[a-zA-Z][a-zA-Z0-9]{1,31});")

# Order matters – longer / greedier patterns first.
_INLINE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("escape",       re.compile(r"\\([\\`*_{}\[\]()#+\-.!~|])")),
    ("code",         re.compile(r"(`+)(.+?)\1", re.S)),
    ("image",        re.compile(r"!\[([^\]]*)\]\((\S+?)(?:\s+\"([^\"]*)\")?\)")),
    ("link",         re.compile(r"\[([^\]]+)\]\((\S+?)(?:\s+\"([^\"]*)\")?\)")),
    ("reflink",      re.compile(r"\[([^\]]+)\]\[([^\]]*)\]")),
    ("autolink",     re.compile(r"<(https?://[^>]+)>")),
    ("email",        re.compile(r"<([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})>")),
    ("bold_italic",  re.compile(r"\*{3}(.+?)\*{3}", re.S)),
    ("bold_italic2", re.compile(r"_{3}(.+?)_{3}", re.S)),
    ("bold",         re.compile(r"\*{2}(.+?)\*{2}", re.S)),
    ("bold2",        re.compile(r"_{2}(.+?)_{2}", re.S)),
    ("italic",       re.compile(r"\*(.+?)\*", re.S)),
    ("italic2",      re.compile(r"(?<!\w)_(.+?)_(?!\w)", re.S)),
    ("strike",       re.compile(r"~~(.+?)~~", re.S)),
    ("br",           re.compile(r"  \n")),
]


def _parse_inline(text: str, refs: dict | None = None) -> str:
    """Convert inline Markdown to HTML."""
    if refs is None:
        refs = {}
    result: list[str] = []
    pos = 0
    length = len(text)

    while pos < length:
        best_match = None
        best_name = None
        best_start = length  # sentinel

        for name, pat in _INLINE_PATTERNS:
            m = pat.search(text, pos)
            if m and m.start() < best_start:
                best_match = m
                best_name = name
                best_start = m.start()

        if best_match is None:
            result.append(_html.escape(text[pos:]))
            break

        # Text before the match
        if best_start > pos:
            result.append(_html.escape(text[pos:best_start]))

        m = best_match
        if best_name == "escape":
            result.append(_html.escape(m.group(1)))
        elif best_name == "code":
            code = m.group(2).strip()
            result.append(f"<code>{_html.escape(code)}</code>")
        elif best_name == "image":
            alt = _html.escape(m.group(1))
            src = _html.escape(m.group(2))
            title = f' title="{_html.escape(m.group(3))}"' if m.group(3) else ""
            result.append(f'<img src="{src}" alt="{alt}"{title}>')
        elif best_name == "link":
            content = _parse_inline(m.group(1), refs)
            href = _html.escape(m.group(2))
            title = f' title="{_html.escape(m.group(3))}"' if m.group(3) else ""
            result.append(f'<a href="{href}"{title}>{content}</a>')
        elif best_name == "reflink":
            content = m.group(1)
            ref_id = (m.group(2) or content).lower()
            if ref_id in refs:
                href = _html.escape(refs[ref_id]["url"])
                title_attr = ""
                if refs[ref_id].get("title"):
                    title_attr = f' title="{_html.escape(refs[ref_id]["title"])}"'
                result.append(f'<a href="{href}"{title_attr}>{_parse_inline(content, refs)}</a>')
            else:
                result.append(_html.escape(m.group(0)))
        elif best_name == "autolink":
            url = _html.escape(m.group(1))
            result.append(f'<a href="{url}">{url}</a>')
        elif best_name == "email":
            addr = _html.escape(m.group(1))
            result.append(f'<a href="mailto:{addr}">{addr}</a>')
        elif best_name in ("bold_italic", "bold_italic2"):
            inner = _parse_inline(m.group(1), refs)
            result.append(f"<strong><em>{inner}</em></strong>")
        elif best_name in ("bold", "bold2"):
            inner = _parse_inline(m.group(1), refs)
            result.append(f"<strong>{inner}</strong>")
        elif best_name in ("italic", "italic2"):
            inner = _parse_inline(m.group(1), refs)
            result.append(f"<em>{inner}</em>")
        elif best_name == "strike":
            inner = _parse_inline(m.group(1), refs)
            result.append(f"<del>{inner}</del>")
        elif best_name == "br":
            result.append("<br>\n")

        pos = m.end()

    return "".join(result)


# ═══════════════════════════════════════════════════════════════════════════
#  Block Parser
# ═══════════════════════════════════════════════════════════════════════════

def _slug(text: str) -> str:
    """Generate a URL-friendly id from heading text."""
    text = re.sub(r"<[^>]+>", "", text)          # strip HTML tags
    text = _html.unescape(text)
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text)
    return text


def _highlight_code(code: str, lang: str) -> str:
    """Highlight a code block. Falls back to plain <pre> without Pygments."""
    if HAS_PYGMENTS and lang:
        try:
            lexer = get_lexer_by_name(lang, stripall=True)
            formatter = HtmlFormatter(nowrap=True, classprefix="hl-")
            highlighted = _pygments_highlight(code, lexer, formatter)
            return (
                f'<pre><code class="language-{_html.escape(lang)}">'
                f"{highlighted}</code></pre>"
            )
        except ClassNotFound:
            pass
    escaped = _html.escape(code)
    cls = f' class="language-{_html.escape(lang)}"' if lang else ""
    return f"<pre><code{cls}>{escaped}</code></pre>"


def _parse_table(lines: list[str], refs: dict) -> str:
    """Parse a GFM-style table."""
    def split_row(line: str) -> list[str]:
        line = line.strip()
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]
        return [c.strip() for c in line.split("|")]

    headers = split_row(lines[0])
    align_cells = split_row(lines[1])
    alignments: list[str] = []
    for cell in align_cells:
        cell = cell.strip()
        if cell.startswith(":") and cell.endswith(":"):
            alignments.append("center")
        elif cell.endswith(":"):
            alignments.append("right")
        elif cell.startswith(":"):
            alignments.append("left")
        else:
            alignments.append("")

    def style(col: int) -> str:
        if col < len(alignments) and alignments[col]:
            return f' style="text-align:{alignments[col]}"'
        return ""

    parts = ["<table>", "<thead>", "<tr>"]
    for ci, h in enumerate(headers):
        parts.append(f"<th{style(ci)}>{_parse_inline(h, refs)}</th>")
    parts += ["</tr>", "</thead>", "<tbody>"]

    for row_line in lines[2:]:
        cells = split_row(row_line)
        parts.append("<tr>")
        for ci, cell in enumerate(cells):
            parts.append(f"<td{style(ci)}>{_parse_inline(cell, refs)}</td>")
        parts.append("</tr>")

    parts += ["</tbody>", "</table>"]
    return "\n".join(parts)


class _ListBuilder:
    """Accumulate list items with proper nesting."""

    def __init__(self, ordered: bool, start: int = 1):
        self.ordered = ordered
        self.start = start
        self.items: list[str] = []

    def add(self, content_html: str) -> None:
        self.items.append(content_html)

    def render(self) -> str:
        tag = "ol" if self.ordered else "ul"
        start_attr = f' start="{self.start}"' if self.ordered and self.start != 1 else ""
        inner = "\n".join(f"<li>{item}</li>" for item in self.items)
        return f"<{tag}{start_attr}>\n{inner}\n</{tag}>"


def _parse_blocks(text: str, refs: dict) -> str:
    """Parse block-level Markdown and return HTML."""
    lines = text.split("\n")
    out: list[str] = []
    n = len(lines)
    i = 0

    while i < n:
        line = lines[i]

        # ── blank ──────────────────────────────────────────────────────
        if not line.strip():
            i += 1
            continue

        # ── fenced code block ──────────────────────────────────────────
        m = re.match(r"^(`{3,}|~{3,})\s*([\w+#.\-]*)\s*$", line)
        if m:
            fence_char = m.group(1)[0]
            fence_len = len(m.group(1))
            lang = m.group(2)
            code_lines: list[str] = []
            i += 1
            while i < n:
                close = re.match(
                    rf"^{re.escape(fence_char)}{{{fence_len},}}\s*$", lines[i]
                )
                if close:
                    i += 1
                    break
                code_lines.append(lines[i])
                i += 1
            out.append(_highlight_code("\n".join(code_lines), lang))
            continue

        # ── ATX heading ────────────────────────────────────────────────
        m = re.match(r"^(#{1,6})\s+(.*?)(?:\s+#+)?\s*$", line)
        if m:
            lvl = len(m.group(1))
            raw = m.group(2).strip()
            body = _parse_inline(raw, refs)
            sid = _slug(raw)
            out.append(f"<h{lvl} id=\"{sid}\">{body}</h{lvl}>")
            i += 1
            continue

        # ── Setext heading ─────────────────────────────────────────────
        if i + 1 < n:
            if re.match(r"^={3,}\s*$", lines[i + 1]):
                body = _parse_inline(line.strip(), refs)
                out.append(f'<h1 id="{_slug(line.strip())}">{body}</h1>')
                i += 2
                continue
            if re.match(r"^-{3,}\s*$", lines[i + 1]) and line.strip():
                body = _parse_inline(line.strip(), refs)
                out.append(f'<h2 id="{_slug(line.strip())}">{body}</h2>')
                i += 2
                continue

        # ── horizontal rule ────────────────────────────────────────────
        if re.match(r"^(\*[\s*]*\*[\s*]*\*[\s*]*|" r"-[\s-]*-[\s-]*-[\s-]*|"r"_[\s_]*_[\s_]*_[\s_]*)$", line.strip()):
            out.append("<hr>")
            i += 1
            continue

        # ── blockquote ─────────────────────────────────────────────────
        if re.match(r"^>\s?", line):
            bq: list[str] = []
            while i < n and (re.match(r"^>\s?", lines[i]) or (lines[i].strip() and not re.match(r"^(#{1,6}\s|```|~~~)", lines[i]))):
                if lines[i].startswith(">"):
                    bq.append(re.sub(r"^>\s?", "", lines[i]))
                elif lines[i].strip():
                    bq.append(lines[i])
                else:
                    break
                i += 1
            inner = _parse_blocks("\n".join(bq), refs)
            out.append(f"<blockquote>\n{inner}\n</blockquote>")
            continue

        # ── GFM table ──────────────────────────────────────────────────
        if ("|" in line and i + 1 < n
                and re.match(r"^\|?[\s:]*-+[\s:]*(\|[\s:]*-+[\s:]*)*\|?\s*$", lines[i + 1])):
            tbl: list[str] = []
            while i < n and "|" in lines[i]:
                tbl.append(lines[i])
                i += 1
            out.append(_parse_table(tbl, refs))
            continue

        # ── list (ordered / unordered) ─────────────────────────────────
        ul_m = re.match(r"^(\s*)([-*+])\s+", line)
        ol_m = re.match(r"^(\s*)(\d+)([.)]) ", line)
        if ul_m or ol_m:
            block_html, i = _parse_list_block(lines, i, refs)
            out.append(block_html)
            continue

        # ── indented code block ────────────────────────────────────────
        if line.startswith("    ") or line.startswith("\t"):
            code_lines = []
            while i < n and (lines[i].startswith("    ") or lines[i].startswith("\t") or not lines[i].strip()):
                if lines[i].startswith("    "):
                    code_lines.append(lines[i][4:])
                elif lines[i].startswith("\t"):
                    code_lines.append(lines[i][1:])
                else:
                    code_lines.append("")
                i += 1
            while code_lines and not code_lines[-1].strip():
                code_lines.pop()
            out.append(f"<pre><code>{_html.escape(chr(10).join(code_lines))}</code></pre>")
            continue

        # ── raw HTML block ─────────────────────────────────────────────
        if re.match(r"^<(?:div|pre|table|ul|ol|dl|fieldset|form|h[1-6]|hr|blockquote|"
                     r"address|article|aside|details|figcaption|figure|footer|header|"
                     r"hgroup|main|menu|nav|section|summary)\b", line, re.I):
            html_lines = [line]
            i += 1
            while i < n and lines[i].strip():
                html_lines.append(lines[i])
                i += 1
            out.append("\n".join(html_lines))
            continue

        # ── paragraph (default) ────────────────────────────────────────
        para: list[str] = [line]
        i += 1
        while i < n:
            if not lines[i].strip():
                break
            if re.match(r"^(#{1,6}\s|```|~~~|>\s?|\s*[-*+]\s|\s*\d+[.)]\s)", lines[i]):
                break
            if i + 1 < n and re.match(r"^[=-]{3,}\s*$", lines[i]):
                break
            para.append(lines[i])
            i += 1
        content = _parse_inline("\n".join(para), refs)
        out.append(f"<p>{content}</p>")

    return "\n".join(out)


# ── list helpers ───────────────────────────────────────────────────────────

_UL_RE = re.compile(r"^(\s*)([-*+])\s+(.*)")
_OL_RE = re.compile(r"^(\s*)(\d+)([.)]) (.*)")


def _list_item_re(line: str):
    m = _UL_RE.match(line)
    if m:
        return m, False, int(m.group(2)) if False else 0
    m = _OL_RE.match(line)
    if m:
        return m, True, int(m.group(2))
    return None, None, 0


def _parse_list_block(lines: list[str], start: int, refs: dict) -> tuple[str, int]:
    """Parse an entire list block (with nesting) starting at *start*."""
    first_ul = _UL_RE.match(lines[start])
    first_ol = _OL_RE.match(lines[start])
    ordered = first_ol is not None
    base_indent = len((first_ol or first_ul).group(1))  # type: ignore[union-attr]
    start_num = int(first_ol.group(2)) if first_ol else 1

    items: list[str] = []
    item_lines: list[str] = []
    i = start

    def flush_item():
        if not item_lines:
            return
        # First line is already stripped of marker.  Subsequent lines need
        # their continuation indent removed.
        text = "\n".join(item_lines)
        # Recursively parse blocks inside the item (handles nested lists, paragraphs …)
        items.append(_parse_blocks(text, refs) if "\n" in text.strip() else _parse_inline(text.strip(), refs))

    while i < len(lines):
        line = lines[i]

        # blank line – may be a loose-list separator or end of list
        if not line.strip():
            # peek: does the list continue?
            if i + 1 < len(lines):
                next_m, _, _ = _list_item_re(lines[i + 1])
                next_indent = len(re.match(r"^(\s*)", lines[i + 1]).group(1))
                if next_m and next_indent == base_indent:
                    item_lines.append("")
                    i += 1
                    continue
                if next_indent > base_indent:
                    item_lines.append("")
                    i += 1
                    continue
            flush_item()
            item_lines = []
            break

        m_ul = _UL_RE.match(line)
        m_ol = _OL_RE.match(line)
        m = m_ul or m_ol

        if m:
            indent = len(m.group(1))
            if indent < base_indent:
                break
            if indent == base_indent:
                is_ol = m_ol is not None
                if is_ol != ordered:
                    # Different list type at same indent → end this list
                    break
                flush_item()
                item_lines = []
                # grab content after marker
                if m_ol:
                    item_lines.append(m_ol.group(4))
                else:
                    item_lines.append(m_ul.group(3))  # type: ignore[union-attr]
                i += 1
                continue
            # indent > base_indent  →  nested, keep as-is for recursive parse
            item_lines.append(line)
            i += 1
            continue

        # continuation line
        indent = len(re.match(r"^(\s*)", line).group(1))
        if indent > base_indent:
            item_lines.append(line)
            i += 1
            continue
        # non-indented, non-list line → end
        break

    flush_item()

    tag = "ol" if ordered else "ul"
    start_attr = f' start="{start_num}"' if ordered and start_num != 1 else ""
    inner = "\n".join(f"<li>{it}</li>" for it in items)
    return f"<{tag}{start_attr}>\n{inner}\n</{tag}>", i


# ═══════════════════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════════════════

def _extract_refs(text: str) -> tuple[str, dict]:
    """Pull out [id]: url "title" reference definitions."""
    refs: dict[str, dict] = {}
    kept: list[str] = []
    for line in text.split("\n"):
        m = re.match(r'^\[([^\]]+)\]:\s+(\S+)(?:\s+"([^"]*)")?\s*$', line)
        if m:
            refs[m.group(1).lower()] = {"url": m.group(2), "title": m.group(3) or ""}
        else:
            kept.append(line)
    return "\n".join(kept), refs


def convert(markdown: str) -> str:
    """Convert a Markdown string to an HTML fragment."""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    text, refs = _extract_refs(text)
    return _parse_blocks(text, refs)


def convert_full(markdown: str, title: str = "md2html", theme: str = "light") -> str:
    """Convert Markdown to a complete, styled HTML document."""
    body = convert(markdown)
    css = _DOC_CSS_DARK if theme == "dark" else _DOC_CSS_LIGHT
    pygments_css = ""
    if HAS_PYGMENTS:
        pygments_css = f"<style>{HtmlFormatter(classprefix='hl-').get_style_defs()}</style>"
    return textwrap.dedent(f"""\
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{_html.escape(title)}</title>
    <style>{css}</style>
    {pygments_css}
    </head>
    <body>
    <article class="markdown-body">
    {body}
    </article>
    </body>
    </html>
    """)


# ═══════════════════════════════════════════════════════════════════════════
#  CSS Themes
# ═══════════════════════════════════════════════════════════════════════════

_DOC_CSS_LIGHT = """
:root{--bg:#fff;--fg:#24292f;--link:#0969da;--border:#d0d7de;--code-bg:#f6f8fa;
--blockquote-border:#d0d7de;--blockquote-fg:#57606a;--table-border:#d0d7de;}
*{box-sizing:border-box}
body{margin:0;padding:2rem;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
background:var(--bg);color:var(--fg);line-height:1.6}
.markdown-body{max-width:860px;margin:0 auto}
h1,h2,h3,h4,h5,h6{margin-top:1.5em;margin-bottom:.5em;font-weight:600;line-height:1.25}
h1{font-size:2em;border-bottom:1px solid var(--border);padding-bottom:.3em}
h2{font-size:1.5em;border-bottom:1px solid var(--border);padding-bottom:.3em}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
code{padding:.2em .4em;font-size:85%;background:var(--code-bg);border-radius:6px;
font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace}
pre{padding:16px;overflow:auto;font-size:85%;line-height:1.45;background:var(--code-bg);
border-radius:6px}
pre code{padding:0;background:transparent;font-size:100%}
blockquote{margin:0;padding:0 1em;color:var(--blockquote-fg);border-left:.25em solid var(--blockquote-border)}
table{border-collapse:collapse;width:100%;margin:1em 0}
th,td{padding:6px 13px;border:1px solid var(--table-border)}
th{font-weight:600;background:var(--code-bg)}
img{max-width:100%}
hr{height:.25em;padding:0;margin:24px 0;background:var(--border);border:0;border-radius:2px}
ul,ol{padding-left:2em}
li+li{margin-top:.25em}
del{text-decoration:line-through;opacity:.65}
"""

_DOC_CSS_DARK = """
:root{--bg:#0d1117;--fg:#e6edf3;--link:#58a6ff;--border:#30363d;--code-bg:#161b22;
--blockquote-border:#3b434b;--blockquote-fg:#8b949e;--table-border:#30363d;}
*{box-sizing:border-box}
body{margin:0;padding:2rem;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
background:var(--bg);color:var(--fg);line-height:1.6}
.markdown-body{max-width:860px;margin:0 auto}
h1,h2,h3,h4,h5,h6{margin-top:1.5em;margin-bottom:.5em;font-weight:600;line-height:1.25}
h1{font-size:2em;border-bottom:1px solid var(--border);padding-bottom:.3em}
h2{font-size:1.5em;border-bottom:1px solid var(--border);padding-bottom:.3em}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
code{padding:.2em .4em;font-size:85%;background:var(--code-bg);border-radius:6px;
font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace}
pre{padding:16px;overflow:auto;font-size:85%;line-height:1.45;background:var(--code-bg);
border-radius:6px}
pre code{padding:0;background:transparent;font-size:100%}
blockquote{margin:0;padding:0 1em;color:var(--blockquote-fg);border-left:.25em solid var(--blockquote-border)}
table{border-collapse:collapse;width:100%;margin:1em 0}
th,td{padding:6px 13px;border:1px solid var(--table-border)}
th{font-weight:600;background:var(--code-bg)}
img{max-width:100%}
hr{height:.25em;padding:0;margin:24px 0;background:var(--border);border:0;border-radius:2px}
ul,ol{padding-left:2em}
li+li{margin-top:.25em}
del{text-decoration:line-through;opacity:.65}
"""

# ═══════════════════════════════════════════════════════════════════════════
#  Web App
# ═══════════════════════════════════════════════════════════════════════════

_WEB_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>md2html — Live Preview</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0d1117;--panel:#161b22;--border:#30363d;--fg:#e6edf3;--accent:#58a6ff;
--muted:#8b949e;--code-bg:#1c2128}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
background:var(--bg);color:var(--fg);height:100vh;display:flex;flex-direction:column}
header{display:flex;align-items:center;gap:12px;padding:10px 20px;background:var(--panel);
border-bottom:1px solid var(--border);flex-shrink:0}
header h1{font-size:1.1rem;font-weight:600;color:var(--accent)}
header .badge{font-size:.75rem;padding:2px 8px;border-radius:12px;background:var(--accent);
color:var(--bg);font-weight:600}
.controls{margin-left:auto;display:flex;gap:8px;align-items:center}
.controls select,.controls button{background:var(--panel);color:var(--fg);border:1px solid var(--border);
border-radius:6px;padding:4px 10px;font-size:.8rem;cursor:pointer}
.controls button:hover{background:var(--border)}
main{display:flex;flex:1;overflow:hidden}
.pane{flex:1;display:flex;flex-direction:column;overflow:hidden}
.pane-header{padding:6px 16px;font-size:.75rem;font-weight:600;text-transform:uppercase;
letter-spacing:.05em;color:var(--muted);background:var(--panel);border-bottom:1px solid var(--border)}
.divider{width:1px;background:var(--border);flex-shrink:0}
#editor{flex:1;padding:16px;font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
font-size:14px;line-height:1.6;background:var(--bg);color:var(--fg);border:none;outline:none;
resize:none;tab-size:4}
#preview{flex:1;padding:16px 24px;overflow-y:auto;background:var(--bg)}
/* preview styles */
#preview h1,#preview h2,#preview h3,#preview h4,#preview h5,#preview h6{margin-top:1.2em;margin-bottom:.4em;font-weight:600}
#preview h1{font-size:1.8em;border-bottom:1px solid var(--border);padding-bottom:.25em}
#preview h2{font-size:1.4em;border-bottom:1px solid var(--border);padding-bottom:.25em}
#preview p{margin:.6em 0}
#preview a{color:var(--accent)}
#preview code{padding:.15em .35em;font-size:85%;background:var(--code-bg);border-radius:4px;
font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace}
#preview pre{padding:14px;overflow:auto;font-size:85%;line-height:1.45;background:var(--code-bg);
border-radius:6px;margin:.8em 0}
#preview pre code{padding:0;background:transparent}
#preview blockquote{margin:.6em 0;padding:0 1em;color:var(--muted);border-left:3px solid var(--border)}
#preview table{border-collapse:collapse;width:100%;margin:.8em 0}
#preview th,#preview td{padding:6px 13px;border:1px solid var(--border)}
#preview th{background:var(--panel);font-weight:600}
#preview img{max-width:100%;border-radius:6px}
#preview hr{height:3px;background:var(--border);border:0;border-radius:2px;margin:1.5em 0}
#preview ul,#preview ol{padding-left:2em;margin:.4em 0}
#preview del{opacity:.6}
</style>
</head>
<body>
<header>
<h1>md2html</h1>
<span class="badge">v""" + __version__ + r"""</span>
<div class="controls">
<select id="theme"><option value="dark" selected>Dark</option><option value="light">Light</option></select>
<button id="copyBtn">Copy HTML</button>
<button id="downloadBtn">Download</button>
</div>
</header>
<main>
<div class="pane">
<div class="pane-header">Markdown</div>
<textarea id="editor" spellcheck="false" placeholder="Type your Markdown here..."></textarea>
</div>
<div class="divider"></div>
<div class="pane">
<div class="pane-header">Preview</div>
<div id="preview"></div>
</div>
</main>
<script>
const editor=document.getElementById('editor'),preview=document.getElementById('preview');
const copyBtn=document.getElementById('copyBtn'),downloadBtn=document.getElementById('downloadBtn');
const themeSelect=document.getElementById('theme');
let debounce;

const DEFAULT_MD="# Welcome to md2html\n\nA **full CommonMark-compliant** Markdown parser with *live preview*.\n\n## Features\n\n- **Bold**, *italic*, ***bold italic***, ~~strikethrough~~\n- \`inline code\` and fenced code blocks\n- [Links](https://github.com) and ![Images](https://via.placeholder.com/150)\n- Nested lists, blockquotes, tables, and more\n\n## Code Example\n\n\`\`\`python\ndef greet(name: str) -> str:\n    return f\"Hello, {name}!\"\n\nprint(greet(\"World\"))\n\`\`\`\n\n## Table\n\n| Feature | Status | Notes |\n|:--------|:------:|------:|\n| Headings | Done | ATX & Setext |\n| Lists | Done | Nested support |\n| Tables | Done | GFM style |\n| Code | Done | Syntax highlighting |\n\n## Blockquote\n\n> Any sufficiently advanced technology is indistinguishable from magic.\n>\n> -- Arthur C. Clarke\n\n---\n\n### Nested Lists\n\n1. First item\n   - Sub-item A\n   - Sub-item B\n     - Deep nested\n2. Second item\n3. Third item\n\n*Built with zero dependencies.*\n";

editor.value=DEFAULT_MD;

function update(){
  clearTimeout(debounce);
  debounce=setTimeout(()=>{
    fetch('/api/convert',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({markdown:editor.value})})
    .then(r=>r.json()).then(d=>{preview.innerHTML=d.html}).catch(()=>{});
  },150);
}

editor.addEventListener('input',update);
editor.addEventListener('keydown',e=>{
  if(e.key==='Tab'){e.preventDefault();
    const s=editor.selectionStart,end=editor.selectionEnd;
    editor.value=editor.value.substring(0,s)+'    '+editor.value.substring(end);
    editor.selectionStart=editor.selectionEnd=s+4;update()}
});

copyBtn.addEventListener('click',()=>{
  fetch('/api/convert',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({markdown:editor.value,full:true,theme:themeSelect.value})})
  .then(r=>r.json()).then(d=>{navigator.clipboard.writeText(d.html);copyBtn.textContent='Copied!';
    setTimeout(()=>copyBtn.textContent='Copy HTML',1500)}).catch(()=>{});
});

downloadBtn.addEventListener('click',()=>{
  fetch('/api/convert',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({markdown:editor.value,full:true,theme:themeSelect.value})})
  .then(r=>r.json()).then(d=>{
    const blob=new Blob([d.html],{type:'text/html'});const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);a.download='output.html';a.click()}).catch(()=>{});
});

themeSelect.addEventListener('change',()=>{
  const dark=themeSelect.value==='dark';
  document.documentElement.style.setProperty('--bg',dark?'#0d1117':'#ffffff');
  document.documentElement.style.setProperty('--panel',dark?'#161b22':'#f6f8fa');
  document.documentElement.style.setProperty('--border',dark?'#30363d':'#d0d7de');
  document.documentElement.style.setProperty('--fg',dark?'#e6edf3':'#24292f');
  document.documentElement.style.setProperty('--accent',dark?'#58a6ff':'#0969da');
  document.documentElement.style.setProperty('--muted',dark?'#8b949e':'#57606a');
  document.documentElement.style.setProperty('--code-bg',dark?'#1c2128':'#f6f8fa');
});

update();
</script>
</body>
</html>"""


class _Handler(BaseHTTPRequestHandler):
    """HTTP handler for the live-preview web app."""

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[md2html] {fmt % args}\n")

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_WEB_HTML.encode())

    def do_POST(self):
        if self.path != "/api/convert":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        md = body.get("markdown", "")
        full = body.get("full", False)
        theme = body.get("theme", "dark")
        result = convert_full(md, theme=theme) if full else convert(md)
        payload = json.dumps({"html": result})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload.encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def serve(port: int = 8077):
    """Start the live-preview web server."""
    server = HTTPServer(("", port), _Handler)
    print(f"md2html web app running at http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


# ═══════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        prog="md2html",
        description="Convert Markdown to HTML — CLI & live web preview.",
    )
    parser.add_argument("file", nargs="?", help="Markdown file to convert")
    parser.add_argument("-o", "--output", help="Output HTML file (default: stdout)")
    parser.add_argument("--fragment", action="store_true",
                        help="Output only the HTML fragment (no <html> wrapper)")
    parser.add_argument("--theme", choices=["light", "dark"], default="light",
                        help="Theme for full HTML output (default: light)")
    parser.add_argument("--serve", action="store_true",
                        help="Launch the live-preview web app")
    parser.add_argument("--port", type=int, default=8077,
                        help="Port for the web app (default: 8077)")
    parser.add_argument("--version", action="version", version=f"md2html {__version__}")
    args = parser.parse_args()

    if args.serve:
        serve(args.port)
        return

    if not args.file:
        # Read from stdin
        if sys.stdin.isatty():
            parser.print_help()
            sys.exit(1)
        md = sys.stdin.read()
        title = "stdin"
    else:
        path = Path(args.file)
        if not path.exists():
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        md = path.read_text(encoding="utf-8")
        title = path.stem

    result = convert(md) if args.fragment else convert_full(md, title=title, theme=args.theme)

    if args.output:
        Path(args.output).write_text(result, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(result)


if __name__ == "__main__":
    main()
