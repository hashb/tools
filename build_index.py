#!/usr/bin/env python3
"""
build_index.py - Generate index.html with a searchable tool listing.

Scans all *.html files (excluding index.html), extracts the <title> tag,
reads the corresponding *.docs.md for a description, and writes index.html
with embedded JSON + client-side real-time search.
"""

import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).parent

EXCLUDE = {"index.html", "404.html"}

GITHUB_REPO = "hashb/tools"


def get_git_info() -> tuple[str, str]:
    """Return (short_commit, full_commit). Falls back to empty strings."""
    try:
        full = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        short = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
        return short, full
    except Exception:
        return "", ""


def render_footer(year: int, build_time: str, short_commit: str, full_commit: str) -> str:
    build_line = ""
    if short_commit:
        build_line = (
            f'<br>built on {build_time} using commit '
            f'<a href="https://github.com/{GITHUB_REPO}/commit/{full_commit}">'
            f'{short_commit}</a>'
        )
    return f"""\
<small>
  <footer id="footer">
    <p class="copyright">Copyright &copy; <a href="https://chenna.me">Chenna Kautilya</a>, 2011 - {year}.
    <noscript>hello stranger with no javascript ;)</noscript>{build_line}
    </p>
  </footer>
</small>"""


def extract_title(html_path: pathlib.Path) -> str:
    """Return the content of the first <title> tag, or the stem as fallback."""
    text = html_path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return html_path.stem.replace("-", " ").title()


def extract_description(html_path: pathlib.Path) -> str:
    """Return the first paragraph from the matching .docs.md, or ''."""
    docs_path = html_path.with_suffix(".docs.md")
    if not docs_path.exists():
        return ""
    text = docs_path.read_text(encoding="utf-8", errors="replace").strip()
    # Strip HTML comments
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()
    # Return just the first non-empty paragraph (up to 300 chars)
    for para in text.split("\n\n"):
        para = para.strip()
        if para:
            return para[:300]
    return ""


def gather_tools() -> list[dict]:
    tools = []
    for html_path in sorted(ROOT.glob("*.html")):
        if html_path.name in EXCLUDE:
            continue
        title = extract_title(html_path)
        description = extract_description(html_path)
        tools.append(
            {
                "slug": html_path.stem,
                "title": title,
                "description": description,
                "url": html_path.name,
            }
        )
    return tools


INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>tools.chenna.me</title>
  <style>
    :root {{
      --c-bg:        #fdfdfd;
      --c-bg2:       #f8f8f8;
      --c-text:      #333;
      --c-link:      #06c;
      --c-muted:     #666;
      --c-border:    #ddd;
      --c-focus-bg:  #f0f8ff;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --c-bg:       #212121;
        --c-bg2:      #252525;
        --c-text:     #ddd;
        --c-link:     #8cc2dd;
        --c-muted:    #999;
        --c-border:   #444;
        --c-focus-bg: #2a2a2a;
      }}
    }}

    * {{ box-sizing: border-box; }}

    body {{
      font-family: Verdana, sans-serif;
      font-size: 16px;
      line-height: 1.6;
      max-width: 720px;
      margin: 0 auto;
      padding: 20px;
      background: var(--c-bg);
      color: var(--c-text);
    }}

    a {{ color: var(--c-link); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    header {{
      border-bottom: 1px solid var(--c-border);
      margin-bottom: 1.5em;
      padding-bottom: 0.75em;
    }}

    header h1 {{
      margin: 0 0 0.2em;
      font-size: 1.5em;
    }}

    header p {{
      margin: 0;
      font-size: 0.875em;
      color: var(--c-muted);
    }}

    #search {{
      width: 100%;
      padding: 0.4em 0.6em;
      font-size: 1em;
      font-family: inherit;
      border: 1px solid var(--c-border);
      border-radius: 0.25em;
      background: var(--c-bg);
      color: var(--c-text);
      margin-bottom: 1em;
    }}

    #search:focus {{
      outline: none;
      border-color: var(--c-link);
      background: var(--c-focus-bg);
    }}

    #count {{
      font-size: 0.8em;
      color: var(--c-muted);
      margin-bottom: 1em;
    }}

    ul#tool-list {{
      list-style: none;
      margin: 0;
      padding: 0;
    }}

    ul#tool-list li {{
      padding: 0.6em 0;
      border-bottom: 1px solid var(--c-border);
    }}

    ul#tool-list li:last-child {{
      border-bottom: none;
    }}

    .tool-title {{
      font-weight: bold;
    }}

    .tool-desc {{
      font-size: 0.85em;
      color: var(--c-muted);
      margin: 0.15em 0 0;
    }}

    #no-results {{
      display: none;
      color: var(--c-muted);
      font-size: 0.9em;
      margin-top: 1em;
    }}

    footer {{
      border-top: 1px solid var(--c-border);
      margin-top: 2em;
      padding-top: 0.75em;
      font-size: 0.8em;
      color: var(--c-muted);
    }}

    footer a {{ color: var(--c-muted); }}
    footer a:hover {{ color: var(--c-link); }}
  </style>
</head>
<body>

<header>
  <h1><a href="/">tools.chenna.me</a></h1>
  <p>Assorted useful tools, almost entirely generated using LLMs</p>
</header>

<input id="search" type="search" placeholder="Search tools&hellip;" autofocus autocomplete="off">
<div id="count"></div>
<ul id="tool-list"></ul>
<p id="no-results">No tools match your search.</p>

{footer}

<script>
const TOOLS = {tools_json};

const list = document.getElementById('tool-list');
const countEl = document.getElementById('count');
const noResults = document.getElementById('no-results');
const searchInput = document.getElementById('search');

function render(tools) {{
  list.innerHTML = '';
  tools.forEach(t => {{
    const li = document.createElement('li');
    li.innerHTML =
      '<div class="tool-title"><a href="' + esc(t.url) + '">' + esc(t.title) + '</a></div>' +
      (t.description ? '<p class="tool-desc">' + esc(t.description) + '</p>' : '');
    list.appendChild(li);
  }});
  const n = tools.length;
  countEl.textContent = n === TOOLS.length
    ? n + ' tool' + (n !== 1 ? 's' : '')
    : n + ' of ' + TOOLS.length + ' tool' + (TOOLS.length !== 1 ? 's' : '');
  noResults.style.display = n === 0 ? 'block' : 'none';
}}

function esc(s) {{
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

function filter(q) {{
  if (!q) return TOOLS;
  q = q.toLowerCase();
  return TOOLS.filter(t =>
    t.title.toLowerCase().includes(q) ||
    t.description.toLowerCase().includes(q) ||
    t.slug.toLowerCase().includes(q)
  );
}}

searchInput.addEventListener('input', () => render(filter(searchInput.value.trim())));

render(TOOLS);
</script>
</body>
</html>
"""


PAGE_404_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>404 - Page Not Found | tools.chenna.me</title>
  <style>
    :root {{
      --c-bg:        #fdfdfd;
      --c-text:      #333;
      --c-link:      #06c;
      --c-muted:     #666;
      --c-border:    #ddd;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --c-bg:       #212121;
        --c-text:     #ddd;
        --c-link:     #8cc2dd;
        --c-muted:    #999;
        --c-border:   #444;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: Verdana, sans-serif;
      font-size: 16px;
      line-height: 1.6;
      max-width: 720px;
      margin: 0 auto;
      padding: 20px;
      background: var(--c-bg);
      color: var(--c-text);
    }}
    a {{ color: var(--c-link); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    header {{
      border-bottom: 1px solid var(--c-border);
      margin-bottom: 1.5em;
      padding-bottom: 0.75em;
    }}
    header h1 {{ margin: 0 0 0.2em; font-size: 1.5em; }}
    header p {{ margin: 0; font-size: 0.875em; color: var(--c-muted); }}
    .error-container {{ text-align: center; padding: 3em 0; }}
    .error-code {{ font-size: 6em; font-weight: bold; margin: 0 0 0.2em; color: var(--c-muted); line-height: 1; }}
    .error-message {{ font-size: 1.2em; margin-bottom: 1.5em; }}
    footer {{ border-top: 1px solid var(--c-border); margin-top: 2em; padding-top: 0.75em; font-size: 0.8em; color: var(--c-muted); }}
    footer a {{ color: var(--c-muted); }}
    footer a:hover {{ color: var(--c-link); }}
  </style>
</head>
<body>
<header>
  <h1><a href="/">tools.chenna.me</a></h1>
  <p>Assorted useful tools, almost entirely generated using LLMs</p>
</header>
<div class="error-container">
  <p class="error-code">404</p>
  <p class="error-message"><strong>Page not found :(</strong></p>
  <p>The requested page could not be found. <a href="/">Back to tools</a></p>
</div>
{footer}
</body>
</html>
"""


def build():
    now = datetime.now(timezone.utc)
    build_time = now.strftime("%Y-%m-%d %H:%M UTC")
    year = now.year
    short_commit, full_commit = get_git_info()
    footer = render_footer(year, build_time, short_commit, full_commit)

    tools = gather_tools()
    if not tools:
        print("No tools found — nothing to do.", file=sys.stderr)
        return

    tools_json = json.dumps(tools, ensure_ascii=False, indent=2)
    index_html = INDEX_TEMPLATE.format(tools_json=tools_json, footer=footer)
    (ROOT / "index.html").write_text(index_html, encoding="utf-8")
    print(f"Wrote index.html with {len(tools)} tool(s).")

    page404_html = PAGE_404_TEMPLATE.format(footer=footer)
    (ROOT / "404.html").write_text(page404_html, encoding="utf-8")
    print("Wrote 404.html.")


if __name__ == "__main__":
    build()
