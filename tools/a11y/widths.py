#!/usr/bin/env python3
"""WCAG 1.4.10 Reflow gate: no horizontal scrolling at narrow viewports.

Loads the page in exactly-sized iframes (Chrome headless clamps real windows to
~500px) and reports, per width, the document scrollWidth against the frame width
plus the elements whose right edge escapes the viewport.

Usage: python widths.py <tag>
"""
import base64, json, os, re, subprocess, sys

import common

CHROME = common.chrome()
OUT = common.OUT
WORK = common.WORK
WIDTHS = [320, 360, 390, 414, 480, 640, 768, 1024, 1280, 1440]
SPEC = 320  # the width WCAG 1.4.10 names


def build():
    common.scratch_page("clean.html")  # the page under audit, reachable from .work/
    frames = "\n".join(
        '<iframe class="f" data-w="%d" src="clean.html" style="width:%dpx;height:900px"></iframe>'
        % (w, w) for w in WIDTHS)
    html = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>html,body{margin:0;padding:0;background:#fff}
.f{display:block;border:0;position:absolute;left:0;top:-99999px}</style></head><body>
%(frames)s
<script>
window.onerror = function (m) { document.title = 'ERR:' + m; };
var frames = [].slice.call(document.querySelectorAll('iframe.f'));
var left = frames.length;
function diag(doc, win) {
  var vw = win.innerWidth, out = [];
  var els = doc.querySelectorAll('body *');
  for (var i = 0; i < els.length; i++) {
    var el = els[i], r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.right > vw + 1 && out.length < 6) {
      out.push({ tag: el.tagName.toLowerCase(),
                 cls: (el.className || '').toString().slice(0, 60),
                 right: Math.round(r.right) });
    }
  }
  return out;
}
frames.forEach(function (f) {
  f.addEventListener('load', function () {
    var win = f.contentWindow, doc = win.document, tries = 0;
    (function ready() {
      if (doc.readyState !== 'complete') {
        // Bounded: a frame that never settles must fail loudly with the width
        // that hung, instead of dying on the virtual time budget with no clue.
        if (++tries > 40) {
          document.title = 'ERR:frame-not-ready-at-' + f.dataset.w + 'px';
          return;
        }
        setTimeout(ready, 50); return;
      }
      setTimeout(function () {
        var res = { w: +f.dataset.w, vw: win.innerWidth,
                    scrollW: doc.documentElement.scrollWidth,
                    overflowX: doc.documentElement.scrollWidth > win.innerWidth + 1,
                    offenders: diag(doc, win) };
        f.dataset.result = JSON.stringify(res);
        if (--left === 0) {
          var all = frames.map(function (x) { return JSON.parse(x.dataset.result); });
          document.title = 'WIDTHS:' + btoa(unescape(encodeURIComponent(JSON.stringify(all))));
        }
      }, 400);
    })();
  });
});
</script></body></html>""" % {"frames": frames}
    p = os.path.join(WORK, "widths.html")
    open(p, "w", encoding="utf-8").write(html)
    return p


def run(page):
    flags = common.extra_flags() + [
        "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1", "--window-size=1500,1000",
        "--virtual-time-budget=30000", "--no-first-run",
        "--no-default-browser-check", "--allow-file-access-from-files",
        "--user-data-dir=" + os.path.join(WORK, "profile"),
        "file:///" + page.replace("\\", "/").lstrip("/"),
    ]
    dom = subprocess.run([CHROME] + flags + ["--dump-dom"], capture_output=True,
                         text=True, timeout=300, encoding="utf-8", errors="replace")
    err = re.search(r"<title>ERR:([^<]*)</title>", dom.stdout or "")
    if err:
        raise SystemExit("widths probe failed: %s" % err.group(1))
    m = re.search(r"<title>WIDTHS:?([A-Za-z0-9+/=]*)</title>", dom.stdout or "")
    if not m or not m.group(1):
        t = re.search(r"<title>([^<]*)</title>", dom.stdout or "")
        raise SystemExit("widths probe failed: %r" % (t.group(1) if t else None))
    return json.loads(base64.b64decode(m.group(1)).decode())


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "run"
    common.dirs()
    data = run(build())
    with open(os.path.join(OUT, "widths-%s.json" % tag), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    fails = 0
    print("  %-6s %-6s %-8s %s" % ("width", "vw", "scrollW", "verdict"))
    for r in data:
        bad = r["overflowX"]
        if bad:
            fails += 1
        print("  %-6d %-6d %-8d %s" % (r["w"], r["vw"], r["scrollW"],
                                       "OVERFLOW" if bad else "ok"))
        for o in r["offenders"]:
            print("         offender: <%s class=\"%s\"> right=%d" % (o["tag"], o["cls"], o["right"]))
    spec = [r for r in data if r["w"] == SPEC]
    ok_spec = spec and not spec[0]["overflowX"]
    print("\nS1.4.10 (no h-scroll at %dpx): %s" % (SPEC, "PASS" if ok_spec else "FAIL"))
    print("widths with overflow: %d of %d" % (fails, len(data)))
    return 0 if (fails == 0 and ok_spec) else 1


if __name__ == "__main__":
    sys.exit(main())
