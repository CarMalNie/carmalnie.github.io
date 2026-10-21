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

# Element labels the specs assert on, not spec ids.
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


def nav_height(report, viewport):
    """Nav container height as measured in that report, or None if unrecorded."""
    raw = (report.get("raw") or {}).get(viewport) or {}
    value = (raw.get("checks") or {}).get("navHeight")
    return value if isinstance(value, (int, float)) else None


def uniform_mobile_shift(baseline_rows, current_rows, viewport, base_report=None, cur_report=None):
    """Vertical push the taller mobile nav imposes on everything below it.

    Preferred source is the measured difference between the two reports' nav
    heights: the nav is sticky, so it stays in the flow and its height delta is
    exactly what moves the content below it. That is structural, so a single row
    that moved cannot be mistaken for the exemption amount.

    Reports recorded before `navHeight` existed fall back to the most common
    non-nav dy, accepted only when no other delta ties with it and at least three
    rows agree. The fallback requires a positive dy: there the movement has no
    measured cause, so exempting an upward shift could hide a real one.
    """
    if base_report is not None and cur_report is not None:
        before = nav_height(base_report, viewport)
        after = nav_height(cur_report, viewport)
        if before is not None and after is not None:
            return int(round(after - before))

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
        if dx == 0 and same_size and dy > 0:
            deltas[dy] = deltas.get(dy, 0) + 1
    if not deltas:
        return 0
    ranked = sorted(deltas.items(), key=lambda kv: -kv[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return 0  # two candidate deltas tie: exempt nothing rather than pick one
    if ranked[0][1] < 3:
        return 0  # too few rows to call it uniform
    return ranked[0][0]


def moved_only_by(before, after, shift):
    """True when a rect moved by exactly `shift` in y and changed nothing else."""
    return (shift != 0 and before[0] == after[0] and before[2:] == after[2:]
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
    # S3..S7 — structural tokens read from the rendered page, in spec order.
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
    checks.append(("S6 prefers-reduced-motion token exists", bool(meta["css"].get("reducedMotion")),
                   "rules: %s" % (meta["css"].get("reducedMotion") or "none")))
    checks.append(("S7 single main landmark", meta.get("mainLandmarks") == 1,
                   "main elements: %s" % meta.get("mainLandmarks")))
    checks.append(("S7 skip link present", meta.get("skipLink") == 1,
                   "skip links: %s" % meta.get("skipLink")))

    # S7 — differential: nothing else moved or changed color
    base_env = cur_env = None
    base = None
    if baseline_tag:
        base = load(baseline_tag)
        base_env = (base.get("env") or {}).get("platform")
        cur_env = (rep.get("env") or {}).get("platform")
    if baseline_tag and base_env and cur_env and base_env != cur_env:
        # Font metrics and text wrapping differ per platform, so the same page
        # has different rects and a cross-platform diff reports noise as
        # regression. Measured: linux vs win32 turned one 52px nav push into two
        # competing deltas of 52 and 72.
        checks.append(("S7 differential across platforms", None,
                       "baseline measured on %s, this run on %s: rects are not comparable"
                       % (base_env, cur_env)))
    elif baseline_tag:
        bl = rows_by_label(base)
        layout_bad, color_bad = [], []
        shifts = {vp: uniform_mobile_shift(bl, rl, vp, base, rep) for vp in MOBILE_VIEWPORTS}
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
        detail = "; ".join(layout_bad[:6])
        accepted = ", ".join("%s %+dpx" % (k, v) for k, v in sorted(shifts.items()))
        if accepted:
            detail = (detail + " | " if detail else "") + "accepted nav shift: " + accepted
        checks.append(("S7 no layout regression", not layout_bad, detail))
        checks.append(("S7 no unexpected color change", not color_bad, "; ".join(color_bad[:6])))

    width = max(len(c[0]) for c in checks)
    fails = 0
    skipped = 0
    for spec, ok, detail in checks:
        if ok is None:
            status = "SKIP"
            skipped += 1
        elif ok:
            status = "PASS"
        else:
            status = "FAIL"
            fails += 1
        print("%s  %-*s  %s" % (status, width, spec, detail))
    print("\n%d check(s), %d failure(s), %d skipped" % (len(checks), fails, skipped))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
