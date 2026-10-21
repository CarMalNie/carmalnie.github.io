#!/usr/bin/env python3
"""Acceptance spec for the a11y pass on index.html.

Reads out/report-<tag>.json produced by probe.py and asserts each requirement.
An optional baseline tag enables the differential checks (S7).

Usage: python check.py <tag> [baseline-tag]
Exit code 0 = every spec satisfied, 1 = at least one violation.
"""
import json, os, sys

import common

OUT = common.OUT

# spec id -> requirement
HERO = ["hero-eyebrow", "hero-h1", "hero-h2", "hero-lead", "hero-cta-linkedin"]
MUTED = ["proj1-tech", "sub-tech", "ciber-tech", "footer-copyright"]
# Muted lines were deliberately darkened to reach AA: S7 diffs colors, so these
# labels are exempt from that comparison and asserted on their own ratio instead.
INTENDED_COLOR_CHANGE = set(MUTED)
MOBILE_VIEWPORTS = ("hero-mobile", "lower-mobile")

# A row with no usable measurement: clipping or a target smaller than 2x2px.
# MISSING is excluded on purpose: a selector that matches nothing is a defect,
# not something to skip.
UNMEASURABLE = ("OFFSCREEN", "TOO-SMALL")
SKIP = UNMEASURABLE + ("MISSING",)


def intended_layout_change(label, viewport):
    """Nav rects that are allowed to move, and nothing else.

    The mobile nav wraps to two rows below lg. That is the intended fix for a
    real WCAG 1.4.10 violation: the single row of the baseline overflowed at
    320-640px (scrollWidth 662 against a 320px viewport, see widths.py). So S7
    exempts only the nav labels on the mobile viewports; contrast and every
    other rect stay under the differential check.
    """
    return label.startswith("nav-") and viewport.endswith("-mobile")


def uniform_mobile_shift(baseline_rows, current_rows, viewport):
    """Vertical push the taller mobile nav imposes on everything below it.

    The nav is sticky, so it stays in the flow: wrapping to two rows grows it
    from 81px to 133px at 390px and moves every element below by the same
    +52px, with the same x, width and height. That delta is derived from the
    reports (the most common non-nav dy of the viewport) rather than hardcoded,
    and a rect is accepted only when it moved by exactly that much. Anything
    else is still reported as a regression.
    """
    deltas = {}
    for label, per in baseline_rows.items():
        if label.startswith("nav-"):
            continue
        m, n = per.get(viewport), current_rows.get(label, {}).get(viewport)
        if not m or not n or m["status"] in SKIP or n["status"] in SKIP:
            continue
        dx = n["rect"][0] - m["rect"][0]
        dy = n["rect"][1] - m["rect"][1]
        same_size = n["rect"][2:] == m["rect"][2:]
        if dx == 0 and same_size and dy:
            deltas[dy] = deltas.get(dy, 0) + 1
    if not deltas:
        return 0
    ranked = sorted(deltas.items(), key=lambda kv: -kv[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return 0  # two candidate deltas tie: exempt nothing rather than pick one
    return ranked[0][0]


def moved_only_by(before, after, shift):
    """True when a rect moved by exactly `shift` in y and changed nothing else."""
    return (shift > 0 and before[0] == after[0] and before[2:] == after[2:]
            and after[1] - before[1] == shift)


def load(tag):
    with open(os.path.join(OUT, "report-%s.json" % tag), encoding="utf-8") as f:
        return json.load(f)


def rows_by_label(report):
    out = {}
    for vlabel, v in report["variants"].items():
        for m in v["rows"]:
            out.setdefault(m["label"], {})[vlabel] = m
    return out


def main():
    tag = sys.argv[1]
    baseline_tag = sys.argv[2] if len(sys.argv) > 2 else None
    rep = load(tag)
    rl = rows_by_label(rep)
    checks = []  # (spec, ok, detail)

    def assert_pass(labels, viewports, spec):
        for label in labels:
            per = rl.get(label, {})
            seen = 0
            for vp in viewports:
                m = per.get(vp)
                if not m or m["status"] in UNMEASURABLE:
                    continue
                seen += 1
                ok = m["status"] == "PASS"
                checks.append((spec, ok, "%s @%s worst=%.2f need=%.1f"
                               % (label, vp, m.get("worst", 0), m.get("need", 0))))
            if seen == 0:
                checks.append((spec, False, "%s not captured" % label))

    # S1 — WCAG 1.4.3 on the hero (the entry surface)
    assert_pass(HERO, ["hero-desktop", "hero-mobile"], "S1 hero contrast >= AA")
    # S2 — WCAG 1.4.3 on muted/secondary text
    assert_pass(MUTED, ["lower-desktop", "lower-mobile"], "S2 muted contrast >= AA")
    # S3..S6 — structural tokens read from the rendered page
    meta = rep["raw"]["lower-desktop"]["checks"]
    checks.append(("S3 banner is decorative (alt=\"\")", meta.get("bannerAltEmpty") is True,
                   "alt=%r" % meta.get("bannerAlt")))
    checks.append(("S4 icons hidden from AT", meta.get("iconsWithoutAriaHidden") == 0,
                   "%s of %s icons lack aria-hidden"
                   % (meta.get("iconsWithoutAriaHidden"), meta.get("totalAnchorIcons"))))
    bad_links = [l for l in meta.get("footerLinks", []) if not (l.get("ariaLabel") or l.get("text"))]
    checks.append(("S4 footer links have a name", not bad_links,
                   "%d link(s) with only a title attribute" % len(bad_links)))
    checks.append(("S5 focus-visible token exists", bool(meta["css"].get("focusVisible")),
                   "rules: %s" % (meta["css"].get("focusVisible") or "none")))
    checks.append(("S7 single main landmark", meta.get("mainLandmarks") == 1,
                   "main elements: %s" % meta.get("mainLandmarks")))
    checks.append(("S7 skip link present", meta.get("skipLink") == 1,
                   "skip links: %s" % meta.get("skipLink")))
    checks.append(("S6 prefers-reduced-motion token exists", bool(meta["css"].get("reducedMotion")),
                   "rules: %s" % (meta["css"].get("reducedMotion") or "none")))

    # S7 — differential: nothing else moved or changed color
    if baseline_tag:
        base = load(baseline_tag)
        bl = rows_by_label(base)
        layout_bad, color_bad = [], []
        shifts = {vp: uniform_mobile_shift(bl, rl, vp) for vp in MOBILE_VIEWPORTS}
        for label, per in bl.items():
            for vp, m in per.items():
                if m["status"] in SKIP:
                    continue
                n = rl.get(label, {}).get(vp)
                if not n or n["status"] in SKIP:
                    layout_bad.append("%s@%s lost from capture" % (label, vp))
                    continue
                if m["rect"] != n["rect"] and not intended_layout_change(label, vp) \
                        and not moved_only_by(m["rect"], n["rect"], shifts.get(vp, 0)):
                    layout_bad.append("%s@%s rect %s -> %s" % (label, vp, m["rect"], n["rect"]))
                if m["color"] != n["color"] and label not in INTENDED_COLOR_CHANGE:
                    color_bad.append("%s@%s color %s -> %s" % (label, vp, m["color"], n["color"]))
                if m["status"] == "PASS" and n["status"] != "PASS":
                    layout_bad.append("%s@%s regressed to %s" % (label, vp, n["status"]))
        checks.append(("S7 no layout regression", not layout_bad, "; ".join(layout_bad[:6])))
        checks.append(("S7 no unexpected color change", not color_bad, "; ".join(color_bad[:6])))
        checks.append(("S7 mobile shift is the nav delta", all(v > 0 for v in shifts.values()),
                       ", ".join("%s +%dpx" % (k, v) for k, v in sorted(shifts.items()))))

    width = max(len(c[0]) for c in checks)
    fails = 0
    for spec, ok, detail in checks:
        if not ok:
            fails += 1
        print("%s  %-*s  %s" % ("PASS" if ok else "FAIL", width, spec, detail))
    print("\n%d check(s), %d failure(s)" % (len(checks), fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
