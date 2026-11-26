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
chapter in this file), [links](#heading) and [links](NN-chapter.md#heading)
(to a heading) and to the web. No dependencies but Python 3.

Heading anchors, the rule the chapters' links are written by (GitHub's):
the heading's text without its Markdown (** and ` dropped, [label](url) ->
label), in lower case, every character but letters, digits, _, - and the
space removed, then every space -> "-":
  "По Wi-Fi"                          -> #по-wi-fi
  "Сайт приставки: когда он включён"  -> #сайт-приставки-когда-он-включён
A heading whose anchor is already taken in its chapter gets -2, -3, ...
("#установка", "#установка-2"). A link's #anchor is looked up in its own
chapter ([..](#a)) or in the named one ([..](NN-chapter.md#a)); the HTML id
is the anchor, the chapter's first # heading keeps the chapter's id
(ch-NN-name), and an anchor some earlier chapter already uses as an id
gets the next free -N suffix in the HTML (links are resolved, so they
still land on their own chapter's heading).
A link to a chapter or an anchor that does not exist stops the build with
the chapter file and the link (exit status 1, nothing written).
"""
import base64
import html
import os
import re
import sys
import urllib.parse

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


def slug(heading):
    """the heading's anchor by the rule at the top"""
    t = re.sub(r"\[([^\]]+)\]\([^)\s]+\)", r"\1", heading.strip())
    t = t.replace("**", "").replace("`", "").lower()
    return re.sub(r"[^\w\- ]", "", t).replace(" ", "-")


def headings(text):
    """(level, text) of the chapter's # headings, code blocks skipped"""
    out, code = [], False
    for l in text.splitlines():
        if l.startswith("```"):
            code = not code
            continue
        m = None if code else re.match(r"(#{1,3}) (.+)$", l)
        if m:
            out.append((len(m.group(1)), m.group(2)))
    return out


def anchors(chapters):
    """{chapter: {anchor: HTML id}} and {chapter: [HTML id per heading]}
    for {chapter name: its Markdown}, in file name order"""
    used = set(chapter_id(n) for n in chapters)
    amap, ids = {}, {}
    for n in sorted(chapters):
        amap[n], ids[n], first = {}, [], True
        for level, text in headings(chapters[n]):
            base = slug(text)
            a, k = base, 1
            while a in amap[n]:
                k += 1
                a = "%s-%d" % (base, k)
            if first and level == 1:
                hid, first = chapter_id(n), False
            else:
                hid, k = a, 1
                while hid in used:
                    k += 1
                    hid = "%s-%d" % (a, k)
                used.add(hid)
            amap[n][a] = hid
            ids[n].append(hid)
    return amap, ids


class Links:
    """resolves a chapter's local links; broken ones are collected"""
    def __init__(self, amap):
        self.amap, self.errors = amap, []

    def href(self, url, name):
        local = re.fullmatch(r"([0-9]{2}-[a-z0-9-]+\.md)?(?:#(.*))?", url)
        if not local or not url:
            return url
        target, frag = local.group(1) or name, local.group(2)
        if target not in self.amap:
            self.errors.append("%s: link (%s): no chapter %s" % (name, url, target))
            return url
        if frag is None:
            return "#" + chapter_id(target)
        hid = self.amap[target].get(urllib.parse.unquote(frag))
        if hid is None:
            self.errors.append("%s: link (%s): no heading #%s in %s" % (name, url, frag, target))
            return url
        return "#" + hid


def inline(text, name, links):
    """**bold**, `code`, [links](...) of one paragraph's text of chapter
    name, escaped"""
    codes = []

    def keep(m):
        codes.append("<code>%s</code>" % html.escape(m.group(1)))
        return "\0%d\0" % (len(codes) - 1)
    text = re.sub(r"`([^`]+)`", keep, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)

    def link(m):
        label, url = m.group(1), m.group(2)
        href = links.href(html.unescape(url), name)
        return '<a href="%s">%s</a>' % (html.escape(href), label)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
    return re.sub(r"\0(\d+)\0", lambda m: codes[int(m.group(1))], text)


def picture(src, alt, base):
    p = os.path.join(base, src)
    data = base64.b64encode(open(p, "rb").read()).decode()
    mime = "image/png" if p.lower().endswith(".png") else "image/jpeg"
    return ('<figure><img src="data:%s;base64,%s" alt="%s"><figcaption>%s</figcaption></figure>'
            % (mime, data, html.escape(alt), html.escape(alt)))


def table(rows, name, links):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], cells[2:]
    out = ["<table>"]
    if any(head):
        out.append("<tr>" + "".join("<th>%s</th>" % inline(c, name, links) for c in head) + "</tr>")
    for r in body:
        out.append("<tr>" + "".join("<td>%s</td>" % inline(c, name, links) for c in r) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def markdown(text, name, base, ids, links):
    """the chapter's HTML; ids: the HTML id of each heading in order
    (anchors())"""
    lines = text.splitlines()
    out, i, ids = [], 0, iter(ids)
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
            out.append('<h%d id="%s">%s</h%d>' % (level, html.escape(next(ids)),
                                                 inline(m.group(2), name, links), level))
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
            out.append(table(lines[i:j], name, links))
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
            out.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % inline(t, name, links) for t in items), tag))
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r"(#{1,3} |```|\||(-|\d+\.) |!\[)", lines[i]):
            para.append(lines[i].strip())
            i += 1
        out.append("<p>%s</p>" % inline(" ".join(para), name, links))
    return "\n".join(out)


def build(guide=GUIDE):
    chapters_dir = os.path.join(guide, "chapters")
    names = sorted(n for n in os.listdir(chapters_dir) if re.match(r"\d{2}-.+\.md$", n))
    texts = {n: open(os.path.join(chapters_dir, n), encoding="utf-8").read() for n in names}
    amap, ids = anchors(texts)
    links = Links(amap)
    parts, toc = [], []
    for n in names:
        m = re.search(r"^# (.+)$", texts[n], re.M)
        toc.append('<li><a href="#%s">%s</a></li>' % (chapter_id(n), inline(m.group(1) if m else n, n, links)))
        parts.append(markdown(texts[n], n, chapters_dir, ids[n], links))
    if links.errors:
        sys.exit("user-guide.py: broken links:\n  " + "\n  ".join(links.errors))
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
