#!/usr/bin/env python3
"""Shared paths for the a11y harness.

Every script works on the repository's own index.html and keeps its scratch
pages in .work/, so no manual copy of the page or of its assets is needed.

Environment overrides:
  A11Y_PAGE    page to audit (default: <repo>/index.html)
  A11Y_CHROME  Chrome/Chromium executable (default: first one found)
"""
import os
import shutil
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PAGE = os.environ.get("A11Y_PAGE") or os.path.join(ROOT, "index.html")
OUT = os.path.join(HERE, "out")
WORK = os.path.join(HERE, ".work")

_CANDIDATES = [
    os.environ.get("A11Y_CHROME"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def chrome():
    """Path to a real Chrome binary; never guessed silently."""
    for cand in _CANDIDATES:
        if cand and os.path.exists(cand):
            return cand
    found = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium")
    if found:
        return found
    raise SystemExit("Chrome not found: set A11Y_CHROME to the executable path")


def page():
    """The page under audit; fails loudly instead of measuring nothing."""
    if not os.path.exists(PAGE):
        raise SystemExit("page not found: %s (set A11Y_PAGE)" % PAGE)
    return PAGE


def dirs():
    """Create the report and scratch directories; returns (OUT, WORK)."""
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    return OUT, WORK


def base_tag():
    """<base> that resolves the page's relative assets (banner.png) from the repo root.

    Scratch copies live in .work/, so without this every relative asset of the
    page would 404 and the contrast probe would sample blank pixels.
    """
    uri = Path(ROOT).as_uri()
    if not uri.endswith("/"):
        uri += "/"
    return '<base href="%s">' % uri


def scratch_page(name, extra_css=""):
    """Write the page under audit into .work/<name> with the base tag applied."""
    _, work = dirs()
    with open(page(), encoding="utf-8") as f:
        src = f.read()
    inject = base_tag() + extra_css
    if "</head>" in src:
        src = src.replace("</head>", inject + "\n</head>", 1)
    else:  # a fragment without <head>: keep the probe honest instead of guessing
        sys.exit("cannot inject into %s: no </head>" % PAGE)
    path = os.path.join(work, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    return path
