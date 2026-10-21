#!/usr/bin/env python3
"""Rendered a11y probe: WCAG 1.4.3 from real Chrome pixels + structural checks.

Why an iframe: Chrome headless clamps its window to a ~500px minimum width, so
a real 390px phone viewport cannot be requested directly. The target is loaded
inside an exactly-sized iframe instead, which gives true CSS media/vh behaviour.

Contrast method: every glyph is made invisible with -webkit-text-fill-color
(does not change `color`, layout or the backdrop), the frame is screenshotted,
and each target's rect is sampled against the real rendered pixels underneath.
`worst` is the contrast at the backdrop luminance extreme: what a strict
auditor measures, not an average.

Usage: python probe.py <tag>   (tag names out/report-<tag>.json)
"""
import base64, json, os, re, subprocess, sys
from PIL import Image

import common

CHROME = common.chrome()
OUT = common.OUT
WORK = common.WORK

SPECS = [
    ["nav-brand", 'nav a[href="#inicio"]', 0],
    ["nav-link-presentacion", 'nav a[href="#presentacion"]', 0],
    ["nav-link-proyectos", 'nav a[href="#proyectos"]', 0],
    ["nav-link-contacto", 'nav a[href="#contacto"]', 0],
    ["nav-github-btn", 'nav a[target="_blank"]', 0],
    ["hero-eyebrow", "#inicio p", 0],
    ["hero-h1", "#inicio h1", 0],
    ["hero-h2", "#inicio h2", 0],
    ["hero-lead", "#inicio p", 1],
    ["hero-cta-proyectos", '#inicio a[href="#proyectos"]', 0],
    ["hero-cta-linkedin", '#inicio a[target="_blank"]', 0],
    ["perfil-h3", "#presentacion h3", 0],
    ["perfil-body-1", "#presentacion .glass p", 0],
    ["perfil-body-3", "#presentacion .glass p", 2],
    ["stack-h4", "#presentacion h4", 0],
    ["stack-tag-python", "#presentacion .flex-wrap span", 0],
    ["stack-tag-django", "#presentacion .flex-wrap span", 1],
    ["stack-tag-html", "#presentacion .flex-wrap span", 9],
    ["stack-tag-procesos", "#presentacion .flex-wrap span", 12],
    ["proyectos-h3", "#proyectos h3", 0],
    ["proyectos-lead", "#proyectos > div > p", 0],
    ["proj1-badge", "#proyectos span.px-3", 0],
    ["proj1-h4", "#proyectos h4", 0],
    ["proj1-body", "#proyectos p.text-xl", 0],
    ["proj1-tech", "#proyectos p.font-mono", 0],
    ["proj2-h4", "#proyectos h4", 1],
    ["proj2-demo-btn", '#proyectos a[href="https://carmalnie.pythonanywhere.com/"]', 0],
    ["sub-h5", "#proyectos h5", 0],
    ["sub-body-400", "#proyectos p.text-gray-400", 0],
    ["sub-tech", "#proyectos p.font-mono", 1],
    ["github-btn-dark", '#proyectos a[href^="https://github.com/"]', 0],
    ["video-btn-outline", '#proyectos a[href^="https://youtu.be/"]', 0],
    ["roadmap-h5", "#proyectos h5", 3],
    ["roadmap-body", "#proyectos .italic p", 0],
    ["ciber-h4", "#proyectos h4", 2],
    ["ciber-body", "#proyectos p.text-xl", 1],
    ["ciber-tech", "#proyectos p.font-mono", 4],
    ["footer-h4", "footer h4", 0],
    ["footer-quote", "footer p", 0],
    ["footer-copyright", "footer p", 1],
]

HIDE_TEXT = """<style id="probe-css">
*, *::before, *::after { -webkit-text-fill-color: transparent !important;
  text-shadow: none !important; }
</style>"""

PARENT = r"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>html,body{margin:0;padding:0;background:#fff;overflow:hidden}
iframe{border:0;display:block;width:%(w)dpx;height:%(h)dpx}</style></head><body>
<iframe id="f" src="%(src)s"></iframe>
<script>
var SPECS = %(specs)s;
window.onerror = function (m) { document.title = 'ERR:' + m; };
function cssomScan(doc) {
  var found = { focusVisible: [], reducedMotion: [], focusAny: [] };
  function walk(rules) {
    for (var i = 0; i < rules.length; i++) {
      var r = rules[i];
      if (r.selectorText && /:focus-visible/.test(r.selectorText) && found.focusVisible.length < 12)
        found.focusVisible.push(r.selectorText.slice(0, 140));
      if (r.selectorText && /:focus(?!-visible)/.test(r.selectorText) && found.focusAny.length < 8)
        found.focusAny.push(r.selectorText.slice(0, 140));
      if (r.conditionText && /prefers-reduced-motion/.test(r.conditionText))
        found.reducedMotion.push(r.conditionText);
      if (r.cssRules) { try { walk(r.cssRules); } catch (e) {} }
    }
  }
  for (var s = 0; s < doc.styleSheets.length; s++) {
    try { walk(doc.styleSheets[s].cssRules); } catch (e) {}
  }
  return found;
}
var f = document.getElementById('f');
f.addEventListener('load', function () {
  var win = f.contentWindow, doc = win.document;
  (function ready() {
    if (doc.readyState !== 'complete') { setTimeout(ready, 50); return; }
    var go = function () {
      setTimeout(function () {
        var fo = f.getBoundingClientRect();
        var out = [];
        for (var i = 0; i < SPECS.length; i++) {
          var label = SPECS[i][0], sel = SPECS[i][1], idx = SPECS[i][2];
          var el = doc.querySelectorAll(sel)[idx];
          if (!el) { out.push({ label: label, missing: true }); continue; }
          var r = el.getBoundingClientRect(), cs = win.getComputedStyle(el);
          out.push({ label: label,
            rect: { x: r.x + fo.x, y: r.y + fo.y - FRAME_SCROLL, w: r.width, h: r.height },
            color: cs.color, fontSize: parseFloat(cs.fontSize),
            fontWeight: parseInt(cs.fontWeight, 10), tag: el.tagName });
        }
        var nav1 = doc.querySelector('nav a[href="#presentacion"]');
        var checks = {
          htmlLang: doc.documentElement.lang,
          bannerAlt: (doc.querySelector('#inicio img') || {}).alt,
          bannerAltEmpty: doc.querySelector('#inicio img')
            ? doc.querySelector('#inicio img').getAttribute('alt') === '' : null,
          footerLinks: [].map.call(doc.querySelectorAll('footer a'), function (a) {
            return { ariaLabel: a.getAttribute('aria-label'),
                     title: a.getAttribute('title'),
                     text: a.textContent.trim(),
                     iconAriaHidden: [].map.call(a.querySelectorAll('i'),
                       function (i) { return i.getAttribute('aria-hidden'); }) };
          }),
          iconsWithoutAriaHidden: [].filter.call(doc.querySelectorAll('a i'),
            function (i) { return i.getAttribute('aria-hidden') !== 'true'; }).length,
          totalAnchorIcons: doc.querySelectorAll('a i').length,
          css: cssomScan(doc),
          navFocusOutline: nav1 ? (function () {
            var cs = win.getComputedStyle(nav1);
            return { outlineStyle: cs.outlineStyle, outlineWidth: cs.outlineWidth,
                     outlineColor: cs.outlineColor, boxShadow: cs.boxShadow.slice(0, 90) };
          })() : null,
          mainLandmarks: doc.querySelectorAll('main').length,
          navHeight: (function () {
            var n = doc.querySelector('nav');
            return n ? Math.round(n.getBoundingClientRect().height) : null;
          })(),
          skipLink: doc.querySelectorAll('a[href^="#"][class*="sr-only"], a.skip-link').length,
          hasReveal: !!doc.querySelector('#inicio .reveal, #inicio [class*="reveal"]')
        };
        document.title = 'PROBE:' + btoa(unescape(encodeURIComponent(JSON.stringify({
          vw: win.innerWidth, vh: win.innerHeight, dpr: win.devicePixelRatio,
          docH: doc.documentElement.scrollHeight,
          scrollW: doc.documentElement.scrollWidth,
          ua: navigator.userAgent,
          overflowX: doc.documentElement.scrollWidth > win.innerWidth + 1,
          checks: checks, items: out }))));
      }, 400);
    };
    if (doc.fonts && doc.fonts.ready) { doc.fonts.ready.then(go); } else { go(); }
  })();
});
</script></body></html>"""


def make_variant(name, hide_hero):
    css = HIDE_TEXT
    if hide_hero:
        css = css.replace("</style>", "#inicio { display: none !important; }\n</style>")
    return common.scratch_page(name, css)


def make_parent(name, src, w, h):
    html = PARENT % {"w": w, "h": h, "src": src, "specs": json.dumps(SPECS)}
    html = html.replace("FRAME_SCROLL", "0")
    path = os.path.join(WORK, name)
    open(path, "w", encoding="utf-8").write(html)
    return path


def run(page, w, h, tag):
    png = os.path.join(WORK, "bd-%s.png" % tag)
    flags = common.extra_flags() + [
        "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--window-size=%d,%d" % (w, min(h, 8100)),
        "--virtual-time-budget=25000", "--no-first-run",
        "--no-default-browser-check", "--disable-lcd-text",
        "--allow-file-access-from-files",
        "--user-data-dir=" + os.path.join(WORK, "profile"),
        "file:///" + page.replace("\\", "/").lstrip("/"),
    ]
    if os.path.exists(png):
        os.remove(png)
    subprocess.run([CHROME] + flags + ["--screenshot=" + png],
                   capture_output=True, timeout=300)
    dom = subprocess.run([CHROME] + flags + ["--dump-dom"],
                         capture_output=True, text=True, timeout=300,
                         encoding="utf-8", errors="replace")
    m = re.search(r"<title>PROBE:([A-Za-z0-9+/=]+)</title>", dom.stdout or "")
    if not m:
        err = re.search(r"<title>([^<]*)</title>", dom.stdout or "")
        raise SystemExit("PROBE FAILED for %s: title=%r" % (tag, err.group(1) if err else None))
    data = json.loads(base64.b64decode(m.group(1)).decode())
    data["png"] = png
    return data


def lum(c):
    def f(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def ratio(a, b):
    l1, l2 = lum(a), lum(b)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def parse_color(s):
    nums = [float(x) for x in re.findall(r"[\d.]+", s)]
    a = nums[3] if len(nums) > 3 else 1.0
    return (nums[0], nums[1], nums[2]), a


def over(fg, bg, a):
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3))


def measure(item, img, frame_h):
    r = item["rect"]
    # sample the element interior: central width, middle height. Stays clear of
    # its own border and any border-radius cap, so only backdrop pixels under
    # the glyphs are measured.
    bw, bh = r["w"], r["h"]
    ix = bw * 0.25 if bw > 24 else 0.0
    x0 = int(round(r["x"] + ix)) + 1
    x1 = int(round(r["x"] + bw - ix)) - 1
    y0 = int(round(r["y"] + bh * 0.2)) + 1
    y1 = int(round(r["y"] + bh * 0.8)) - 1
    if x1 - x0 < 2 or y1 - y0 < 2:
        return {"status": "TOO-SMALL"}
    # A crop whose origin is negative would be padded with black by PIL and the
    # ratio measured against pixels the page never painted.
    if x0 < 0 or y0 < 0 or y1 > frame_h or x1 > img.width:
        return {"status": "OFFSCREEN"}
    crop = img.crop((x0, y0, x1, y1))
    fg, alpha = parse_color(item["color"])
    ext = crop.getextrema()
    worst, worst_px = None, None
    for p in (tuple(e[1] for e in ext), tuple(e[0] for e in ext)):
        c = ratio(over(fg, p, alpha), p)
        if worst is None or c < worst:
            worst, worst_px = c, p
    small = crop.resize((24, 8), Image.BOX)
    vals = sorted(ratio(over(fg, p, alpha), p) for p in small.getdata())
    med = vals[len(vals) // 2]
    large = item["fontSize"] >= 24 or (item["fontSize"] >= 18.66 and item["fontWeight"] >= 700)
    need = 3.0 if large else 4.5
    return {"status": "PASS" if worst >= need else "FAIL", "need": need,
            "worst": round(worst, 2), "median": round(med, 2),
            "fg": [round(c) for c in fg], "alpha": alpha,
            "fontSize": item["fontSize"], "fontWeight": item["fontWeight"],
            "worstBackdropPx": list(worst_px)}


def collect(data, label, frame_h):
    img = Image.open(data["png"]).convert("RGB")
    rows = []
    for item in data["items"]:
        if item.get("missing"):
            rows.append({"label": item["label"], "status": "MISSING"})
            continue
        m = measure(item, img, frame_h)
        m["label"] = item["label"]
        m["rect"] = [round(v) for v in (item["rect"]["x"], item["rect"]["y"],
                                        item["rect"]["w"], item["rect"]["h"])]
        m["color"] = item["color"]
        rows.append(m)
    return {"viewport": label, "rows": rows, "vw": data["vw"], "vh": data["vh"],
            "docH": data["docH"], "scrollW": data["scrollW"],
            "overflowX": data["overflowX"]}


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "run"
    common.dirs()
    va = make_variant("variantA.html", False)   # whole page
    vb = make_variant("variantB.html", True)    # #inicio removed
    runs = [
        ("hero-desktop", "variantA.html", 1440, 900, False),
        ("hero-mobile", "variantA.html", 390, 844, False),
        ("lower-desktop", "variantB.html", 1440, 6200, True),
        ("lower-mobile", "variantB.html", 390, 8600, True),
    ]
    report = {"env": {"platform": sys.platform, "page": common.PAGE}, "variants": {}, "raw": {}}
    for index, (label, src, w, h, fit) in enumerate(runs):
        page = make_parent("page-%s.html" % label, src, w, h)
        data = run(page, w, h + 100, "%s-%s" % (tag, label))
        if fit and data["docH"] > h:  # content clipped: retry tall enough to hold it
            h = data["docH"] + 20
            page = make_parent("page-%s.html" % label, src, w, h)
            data = run(page, w, h + 100, "%s-%s" % (tag, label))
        if index == 0:
            # Provenance: a ratio only means something next to the engine that
            # rendered it, and `chrome --version` answers from a live session.
            report["env"]["user_agent"] = data.get("ua")
        report["variants"][label] = collect(data, label, h)
        report["raw"][label] = {k: v for k, v in data.items() if k not in ("items", "png", "ua")}
        report["raw"][label]["png"] = data["png"]
    with open(os.path.join(OUT, "report-%s.json" % tag), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)

    print("== layout / structural ==")
    for k, v in report["raw"].items():
        print("  %-14s vw=%s vh=%s docH=%s scrollW=%s overflowX=%s"
              % (k, v["vw"], v["vh"], v["docH"], v["scrollW"], v["overflowX"]))
    print(json.dumps(report["raw"]["lower-desktop"]["checks"], indent=1, ensure_ascii=False)[:3000])

    covered, fails = set(), []
    for vlabel, v in report["variants"].items():
        print("\n=== %s ===" % vlabel)
        for m in v["rows"]:
            if m["status"] in ("OFFSCREEN", "TOO-SMALL"):
                continue
            covered.add(m["label"])
            if m["status"] in ("FAIL", "MISSING"):
                fails.append((vlabel, m["label"], m.get("worst"), m["status"]))
                print("  FAIL %-22s need %-4s worst %-6s median %-6s px %s"
                      % (m["label"], m.get("need", "-"), m.get("worst", "-"),
                         m.get("median", "-"), m.get("fontSize", "-")))
    missing = [s[0] for s in SPECS if s[0] not in covered]
    print("\nnot covered by any capture: %s" % missing)
    print("FAILURES: %d" % len(fails))


if __name__ == "__main__":
    main()
