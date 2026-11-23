#!/usr/bin/env python3
"""
user-guide.py OUT.html: the user guide (docs/user-guide: title.html, the
chapters' Markdown in file name order, their pictures) as one HTML file
with everything in it (pictures as data: URIs), to read in any browser.
board/ogu/buildroot/post-build.sh puts it into the rootfs
(/usr/share/doc/user-guide.html); game-install prepare-card copies it to
the games card as "Руководство.html", where the player finds it when the
card is opened on a computer.

Only the Markdown the guide uses: # headings, paragraphs, - and 1. lists
(continued by indented lines), | tables |, ```code blocks```, a picture
alone on its line, **bold**, `code`, [links](NN-chapter.md) (to the
chapter in this file) and to the web. No dependencies but Python 3.
"""
import base64
import html
import os
import re
import sys

GUIDE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "user-guide")

CSS = """
:root { color-scheme: light; }
body { margin: 0; background: #f4f4f2; color: #1d1d1b;
  font: 17px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 24px 18px 64px; background: #fff; }
.titlepage { padding: 48px 0 32px; border-bottom: 2px solid #1d1d1b; margin-bottom: 24px; }
.titlepage .kicker { text-transform: uppercase; letter-spacing: .12em; color: #6b6b66; font-size: 14px; }
.titlepage .title { font-size: 40px; font-weight: 700; line-height: 1.15; margin: 12px 0; }
.titlepage .subtitle { font-size: 20px; color: #3a3a36; }
.titlepage .meta { margin-top: 20px; color: #6b6b66; font-size: 15px; }
nav ol { padding-left: 22px; } nav a { color: #1f5fa8; }
h1 { font-size: 30px; margin: 56px 0 12px; padding-top: 16px; border-top: 1px solid #ddd; }
h2 { font-size: 23px; margin: 32px 0 8px; } h3 { font-size: 19px; margin: 24px 0 6px; }
code { font: 15px/1.4 ui-monospace, Consolas, monospace; background: #f0efe9; padding: 1px 4px;
  border-radius: 3px; }
pre { background: #f0efe9; padding: 12px; overflow-x: auto; border-radius: 4px; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; margin: 12px 0; width: 100%; }
th, td { border: 1px solid #d6d5cf; padding: 6px 9px; vertical-align: top; text-align: left; }
th { background: #f0efe9; }
figure { margin: 16px 0; } figure img { max-width: 100%; border: 1px solid #ccc; border-radius: 4px; }
figcaption { color: #6b6b66; font-size: 14px; }
a { color: #1f5fa8; }
@media print { body { background: #fff; } main { max-width: none; } h1 { break-before: page; } }
"""


def chapter_id(name):
    return "ch-" + os.path.splitext(name)[0]


def inline(text):
    """**bold**, `code`, [links](...) of one paragraph's text, escaped"""
    codes = []

    def keep(m):
        codes.append("<code>%s</code>" % html.escape(m.group(1)))
        return "\0%d\0" % (len(codes) - 1)
    text = re.sub(r"`([^`]+)`", keep, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)

    def link(m):
        label, url = m.group(1), m.group(2)
        local = re.fullmatch(r"([0-9]{2}-[a-z0-9-]+)\.md(#.*)?", url)
        href = "#" + chapter_id(local.group(1) + ".md") if local else url
        return '<a href="%s">%s</a>' % (html.escape(href), label)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
    return re.sub(r"\0(\d+)\0", lambda m: codes[int(m.group(1))], text)


def picture(src, alt, base):
    p = os.path.join(base, src)
    data = base64.b64encode(open(p, "rb").read()).decode()
    mime = "image/png" if p.lower().endswith(".png") else "image/jpeg"
    return ('<figure><img src="data:%s;base64,%s" alt="%s"><figcaption>%s</figcaption></figure>'
            % (mime, data, html.escape(alt), html.escape(alt)))


def table(rows):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], cells[2:]
    out = ["<table>"]
    if any(head):
        out.append("<tr>" + "".join("<th>%s</th>" % inline(c) for c in head) + "</tr>")
    for r in body:
        out.append("<tr>" + "".join("<td>%s</td>" % inline(c) for c in r) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def markdown(text, name, base):
    """the chapter's HTML; its first heading gets the chapter's id"""
    lines = text.splitlines()
    out, i, first = [], 0, True
    while i < len(lines):
        l = lines[i]
        if not l.strip():
            i += 1
            continue
        if l.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre><code>%s</code></pre>" % html.escape("\n".join(lines[i + 1:j])))
            i = j + 1
            continue
        m = re.match(r"(#{1,3}) (.+)$", l)
        if m:
            level = len(m.group(1))
            ident = ' id="%s"' % chapter_id(name) if first and level == 1 else ""
            first = first and level != 1
            out.append("<h%d%s>%s</h%d>" % (level, ident, inline(m.group(2)), level))
            i += 1
            continue
        m = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", l.strip())
        if m:
            out.append(picture(m.group(2), m.group(1), base))
            i += 1
            continue
        if l.startswith("|"):
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            out.append(table(lines[i:j]))
            i = j
            continue
        m = re.match(r"(-|\d+\.) ", l)
        if m:
            ordered = m.group(1) != "-"
            items = []
            while i < len(lines) and (re.match(r"(-|\d+\.) ", lines[i]) or
                                      (lines[i].startswith("  ") and items)):
                if re.match(r"(-|\d+\.) ", lines[i]):
                    items.append(re.sub(r"^(-|\d+\.) ", "", lines[i]))
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            tag = "ol" if ordered else "ul"
            out.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % inline(t) for t in items), tag))
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r"(#{1,3} |```|\||(-|\d+\.) |!\[)", lines[i]):
            para.append(lines[i].strip())
            i += 1
        out.append("<p>%s</p>" % inline(" ".join(para)))
    return "\n".join(out)


def build(guide=GUIDE):
    chapters_dir = os.path.join(guide, "chapters")
    names = sorted(n for n in os.listdir(chapters_dir) if re.match(r"\d{2}-.+\.md$", n))
    parts, toc = [], []
    for n in names:
        text = open(os.path.join(chapters_dir, n), encoding="utf-8").read()
        m = re.search(r"^# (.+)$", text, re.M)
        toc.append('<li><a href="#%s">%s</a></li>' % (chapter_id(n), inline(m.group(1) if m else n)))
        parts.append(markdown(text, n, chapters_dir))
    title = open(os.path.join(guide, "title.html"), encoding="utf-8").read()
    return ("<!doctype html>\n<html lang=\"ru\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<title>Руководство пользователя</title>\n<style>%s</style>\n</head>\n<body>\n<main>\n"
            "%s\n<nav><h2>Содержание</h2><ol>%s</ol></nav>\n%s\n</main>\n</body>\n</html>\n"
            % (CSS, title, "".join(toc), "\n".join(parts)))


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: user-guide.py OUT.html")
    out = sys.argv[1]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(build())


if __name__ == "__main__":
    main()
