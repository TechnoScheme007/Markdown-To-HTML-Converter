# md2html

A full **CommonMark-compliant Markdown to HTML converter** in a single Python file. No dependencies required.

Handles headings, bold, italic, strikethrough, code blocks with syntax highlighting, links, images, nested lists, blockquotes, GFM tables, horizontal rules, and more.

## Quick Start

```bash
# Convert a file (full HTML document)
python md2html.py README.md -o output.html

# Pipe through stdin
cat README.md | python md2html.py > output.html

# HTML fragment only (no wrapper)
python md2html.py README.md --fragment

# Dark theme
python md2html.py README.md --theme dark -o output.html

# Launch live-preview web app
python md2html.py --serve
```

## Installation

```bash
git clone https://github.com/TechnoScheme007/md2html.git
cd md2html

# Optional: syntax highlighting
pip install pygments
```

**Zero dependencies** for core functionality. Pygments is optional and adds syntax highlighting to fenced code blocks.

## CLI Reference

```
usage: md2html [-h] [-o OUTPUT] [--fragment] [--theme {light,dark}]
               [--serve] [--port PORT] [--version] [file]

Convert Markdown to HTML — CLI & live web preview.

positional arguments:
  file                  Markdown file to convert

options:
  -h, --help            show this help message and exit
  -o, --output OUTPUT   Output HTML file (default: stdout)
  --fragment            Output only the HTML fragment (no <html> wrapper)
  --theme {light,dark}  Theme for full HTML output (default: light)
  --serve               Launch the live-preview web app
  --port PORT           Port for the web app (default: 8077)
  --version             show program's version number and exit
```

## Web App

Run `python md2html.py --serve` to launch a live-preview editor at `http://localhost:8077`.

Features:
- Split-pane editor with live preview
- Dark / light theme toggle
- Copy rendered HTML to clipboard
- Download as standalone HTML file
- Tab key support in editor

## Supported Markdown

| Element | Syntax | Notes |
|:--------|:-------|:------|
| Heading | `# H1` through `###### H6` | ATX and Setext styles |
| Bold | `**text**` or `__text__` | |
| Italic | `*text*` or `_text_` | |
| Bold Italic | `***text***` | |
| Strikethrough | `~~text~~` | GFM extension |
| Inline Code | `` `code` `` | |
| Code Block | ` ``` ` or `~~~` | With optional language tag |
| Link | `[text](url)` | With optional title |
| Image | `![alt](url)` | |
| Reference Link | `[text][id]` | |
| Unordered List | `- item` or `* item` | Nested with indentation |
| Ordered List | `1. item` | Auto-numbered |
| Blockquote | `> text` | Recursive nesting |
| Table | GFM pipe tables | Left/center/right alignment |
| Horizontal Rule | `---`, `***`, or `___` | |
| HTML | Raw HTML passthrough | Block-level elements |

## Using as a Library

```python
from md2html import convert, convert_full

# Get an HTML fragment
html_fragment = convert("# Hello\n\nThis is **bold**.")

# Get a complete HTML document
html_doc = convert_full("# Hello", title="My Page", theme="dark")
```

## Project Structure

```
md2html/
  md2html.py      # Everything: parser, CLI, web server
  example.md      # Demo markdown file
  README.md       # This file
  LICENSE          # MIT License
```

## License

MIT
