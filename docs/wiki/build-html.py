#!/usr/bin/env python3
"""
build-html.py: the wiki (docs/wiki/*.md) as HTML pages in docs/wiki/html/,
one page a file with a sidebar of the pages, the pictures copied next to
them (html/img/), so the directory can be opened from a file manager or
put on any web server as it is.

  python3 docs/wiki/build-html.py

Needs the markdown package (python3-markdown; docs/book/build.py uses it
too). Links to .md files become links to .html; links out of the wiki
(../config.md, ../../apps/...) point to the files in the repository.
"""
import html
import os
import re
import shutil

import markdown

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "html")

PAGES = [
    ("Home.md", "Вики проекта"),
    ("01-SDK.md", "1. Устройство SDK"),
    ("02-Boot-and-Disk.md", "2. Загрузка и диски"),
    ("03-bare_app.md", "3. bare_app"),
    ("04-Games.md", "4. Игры: как устроены"),
    ("05-Adding-a-Game.md", "5. Добавление игры"),
    ("06-Pitfalls.md", "6. Нюансы"),
    ("07-Tools.md", "7. Инструменты"),
    ("08-Boards.md", "8. Платы"),
]

CSS = """
:root { --bg:#fff; --fg:#222; --muted:#666; --line:#ddd; --side:#f5f6f8; --link:#1a5fb4; --code:#f3f4f6; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#1b1d21; --fg:#e6e6e6; --muted:#9a9a9a; --line:#3a3d44; --side:#23262c; --link:#79b8ff; --code:#2a2d33; }
  img.diagram, img.shot { background:#fff; }
}
* { box-sizing:border-box; }
body { margin:0; font:16px/1.55 "Segoe UI","Noto Sans","DejaVu Sans",Arial,sans-serif; color:var(--fg); background:var(--bg); }
.wrap { display:flex; min-height:100vh; }
nav { width:260px; flex:none; background:var(--side); border-right:1px solid var(--line); padding:18px 14px; position:sticky; top:0; height:100vh; overflow:auto; }
nav h2 { font-size:15px; margin:0 0 10px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
nav a { display:block; padding:6px 8px; color:var(--fg); text-decoration:none; border-radius:6px; }
nav a:hover { background:rgba(127,127,127,.15); }
nav a.current { background:var(--link); color:#fff; }
nav .toc { margin-top:16px; border-top:1px solid var(--line); padding-top:10px; }
nav .toc a { font-size:13px; padding:3px 8px 3px 16px; color:var(--muted); }
main { flex:1; min-width:0; padding:28px 48px 60px; max-width:1100px; }
h1 { font-size:30px; margin:0 0 18px; }
h2 { font-size:22px; margin:34px 0 10px; border-bottom:1px solid var(--line); padding-bottom:4px; }
h3 { font-size:17px; margin:24px 0 8px; }
a { color:var(--link); }
code { font:14px/1.4 "DejaVu Sans Mono",Consolas,monospace; background:var(--code); padding:1px 4px; border-radius:4px; }
pre { background:var(--code); padding:12px 14px; border-radius:8px; overflow:auto; }
pre code { background:none; padding:0; }
table { border-collapse:collapse; margin:12px 0; width:100%; font-size:15px; }
th, td { border:1px solid var(--line); padding:6px 9px; vertical-align:top; text-align:left; }
th { background:var(--side); }
img { max-width:100%; height:auto; }
img.diagram { display:block; margin:14px auto; border:1px solid var(--line); border-radius:8px; }
img.shot { display:block; margin:14px 0 4px; border:1px solid var(--line); border-radius:6px; }
p > img.shot + em, p > img.diagram + em { display:block; font-size:14px; color:var(--muted); }
figure.shot { margin:16px 0; }
figure.shot img { display:block; border:1px solid var(--line); border-radius:6px; }
figure.shot figcaption { font-size:14px; color:var(--muted); margin-top:4px; }
.shots { display:grid; grid-template-columns:repeat(auto-fill, minmax(420px, 1fr)); gap:16px; }
ul.task-list { list-style:none; padding-left:0; }
footer { margin-top:40px; color:var(--muted); font-size:13px; border-top:1px solid var(--line); padding-top:10px; }
@media (max-width: 900px) { .wrap { display:block; } nav { position:static; height:auto; width:auto; border-right:0; border-bottom:1px solid var(--line); } main { padding:18px; } }
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — OdroidLinux</title>
<link rel="stylesheet" href="wiki.css">
</head>
<body>
<div class="wrap">
<nav>
<h2>OdroidLinux</h2>
{nav}
{toc}
</nav>
<main>
{body}
<footer>OdroidLinux SDK — вики. Источник: docs/wiki/*.md; HTML собран build-html.py.</footer>
</main>
</div>
</body>
</html>
"""


def page_name(md):
    return "index.html" if md == "Home.md" else md[:-3] + ".html"


def fix_links(body):
    """.md links of the wiki -> .html; the rest of the repository as is"""
    def sub(m):
        href = m.group(1)
        target, _, anchor = href.partition("#")
        if target in dict(PAGES):
            href = page_name(target) + ("#" + anchor if anchor else "")
        elif target == "" and anchor:
            pass
        elif not target.startswith(("http:", "https:", "img/")):
            # out of the wiki: the repository's file, one level further up
            href = "../" + href
        return 'href="%s"' % href
    return re.sub(r'href="([^"]+)"', sub, body)


def classify_images(body):
    body = re.sub(r'<img alt="([^"]*)" src="(img/shots/[^"]+)"',
                  r'<img class="shot" alt="\1" src="\2"', body)
    body = re.sub(r'<img alt="([^"]*)" src="(img/[^"]+\.svg)"',
                  r'<img class="diagram" alt="\1" src="\2"', body)
    return body


def toc_html(md_toc):
    """markdown's toc (nested ul) -> flat links of the h2 headings"""
    items = re.findall(r'<a href="(#[^"]+)">([^<]+)</a>', md_toc)
    if not items:
        return ""
    # the top-level entries only: the h1 comes first, then h2 as its children
    out = ['<div class="toc">']
    for href, text in items[1:]:
        out.append('<a href="%s">%s</a>' % (href, text))
    out.append("</div>")
    return "\n".join(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    if os.path.isdir(os.path.join(OUT, "img")):
        shutil.rmtree(os.path.join(OUT, "img"))
    shutil.copytree(os.path.join(HERE, "img"), os.path.join(OUT, "img"),
                    ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    with open(os.path.join(OUT, "wiki.css"), "w", encoding="utf-8") as f:
        f.write(CSS.strip() + "\n")

    nav_all = "\n".join('<a href="%s" class="{cur_%s}">%s</a>' % (page_name(md), md, html.escape(title))
                        for md, title in PAGES)
    for md, title in PAGES:
        src = open(os.path.join(HERE, md), encoding="utf-8").read()
        conv = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list"],
                                 extension_configs={"toc": {"toc_depth": "1-2"}})
        body = conv.convert(src)
        body = classify_images(fix_links(body))
        nav = nav_all
        for m2, _ in PAGES:
            nav = nav.replace("{cur_%s}" % m2, "current" if m2 == md else "")
        page = TEMPLATE.format(title=html.escape(title), nav=nav, toc=toc_html(conv.toc), body=body)
        with open(os.path.join(OUT, page_name(md)), "w", encoding="utf-8") as f:
            f.write(page)
        print(page_name(md))


if __name__ == "__main__":
    main()
