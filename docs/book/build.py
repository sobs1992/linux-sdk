#!/usr/bin/env python3
"""Build a book PDF from <book dir>/chapters/*.md.

    build.py                          docs/book     -> docs/sdk-book.pdf
    build.py docs/dev-book            docs/dev-book -> docs/sdk-dev-book.pdf

Needs: markdown, pygments, weasyprint (pip install markdown pygments weasyprint).
The book dir holds chapters/, title.html and optionally book.css
(otherwise docs/book/book.css is used).

Chapter sources are Markdown. A line
    {{include path/in/sdk [first-last] [lang]}}
is replaced by a code block with that file (or line range) from the SDK,
so listings always match the repository.
"""
import html
import re
import sys
from pathlib import Path

import markdown
from pygments.formatters import HtmlFormatter

TOOLS = Path(__file__).resolve().parent
BOOK = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else TOOLS
SDK = TOOLS.parent.parent
OUT = SDK / "docs" / ("sdk-book.pdf" if BOOK.name == "book" else f"sdk-{BOOK.name}.pdf")

INCLUDE = re.compile(r"^\{\{include\s+(\S+)(?:\s+(\d+)-(\d+))?(?:\s+(\w+))?\s*\}\}$", re.M)
LANG_BY_SUFFIX = {".sh": "bash", ".py": "python", ".md": "markdown", ".txt": "text"}


def include(m):
    path, first, last, lang = m.group(1), m.group(2), m.group(3), m.group(4)
    lines = (SDK / path).read_text().splitlines()
    if first:
        lines = lines[int(first) - 1:int(last)]
        title = f"{path}, строки {first}–{last}"
    else:
        title = path
    if not lang:
        name = Path(path).name
        lang = "make" if name == "Makefile" or name.endswith(".mk") else \
            LANG_BY_SUFFIX.get(Path(path).suffix, "text")
    body = "\n".join(lines)
    return f'<div class="listing-title">{html.escape(title)}</div>\n\n```{lang}\n{body}\n```'


def build_toc(parts):
    """parts: (section class, html). Chapter and appendix titles get their number."""
    items, chapter, appendix = [], 0, 0
    for cls, html_part in parts:
        for level, ident, text in re.findall(r'<h([12]) id="([^"]+)">(.*?)</h\1>', html_part):
            text = re.sub(r"<[^>]+>", "", text)
            if level == "1" and cls == "chapter":
                chapter += 1
                text = f"{chapter}. {text}"
            elif level == "1" and cls == "appendix":
                text = f"{chr(ord('A') + appendix)}. {text}"
                appendix += 1
            items.append(f'<li class="toc{level}"><a href="#{ident}">{text}</a></li>')
    return '<nav id="toc"><h1 class="toc-title">Содержание</h1><ul>' + "".join(items) + "</ul></nav>"


_ids = iter(range(1, 10**6))


def main():
    chapters = sorted((BOOK / "chapters").glob("*.md"))
    md = markdown.Markdown(extensions=[
        "fenced_code", "codehilite", "tables", "admonition", "attr_list", "md_in_html",
        "toc"], extension_configs={
        "codehilite": {"css_class": "hl", "guess_lang": False},
        "toc": {"toc_depth": "1-2", "slugify": lambda s, sep: f"s{next(_ids)}"},
    })
    parts = []
    for ch in chapters:
        src = INCLUDE.sub(include, ch.read_text())
        cls = "front" if ch.name.startswith("00") else ("appendix" if ch.name.startswith("9") else "chapter")
        parts.append((cls, md.reset().convert(src)))
    body = "\n".join(f'<section class="{cls}">\n{h}\n</section>' for cls, h in parts)

    css_file = BOOK / "book.css" if (BOOK / "book.css").exists() else TOOLS / "book.css"
    css = css_file.read_text() + HtmlFormatter(style="friendly").get_style_defs(".hl")
    title = (BOOK / "title.html").read_text()
    m = re.search(r'class="title">(.*?)</div>', title, re.S)
    doc_title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip() if m else BOOK.name
    doc = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>{doc_title}</title><style>{css}</style></head>
<body>{title}{build_toc(parts)}{body}</body></html>"""
    html_out = SDK / "output" / (OUT.stem + ".html")     # intermediate, for previewing in a browser
    html_out.parent.mkdir(exist_ok=True)
    html_out.write_text(doc)

    from weasyprint import HTML
    HTML(string=doc, base_url=str(BOOK)).write_pdf(OUT)
    print(f"{OUT} written")


if __name__ == "__main__":
    sys.exit(main())
