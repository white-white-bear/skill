# -*- coding: utf-8 -*-
"""整页图形：符号表、音高查询表、全书地图。

页面内容的坐标是版式，留在这里；页上写什么字从 i18n 和 content 来。
"""
from __future__ import annotations

from . import theme as T


def draw_chart(bk, x, y, w, h, word, sylls, **_):
    """把一个词的音节音高画成折线，标出零线。"""
    c = bk.c
    ymin, ymax = -8.0, 10.0
    to_y = lambda v: y + (v - ymin) / (ymax - ymin) * h
    for g in (-6, -3, 0, 3, 6, 9):
        yy = to_y(g)
        c.setStrokeColor(bk.th.grey if g == 0 else bk.th.rule)
        c.setLineWidth(0.7 if g == 0 else 0.4)
        c.line(x, yy, x + w, yy)
    c.setFillColor(bk.th.grey)
    c.setFont(bk.th.ipa_font, 5.2)
    c.drawRightString(x - 2, to_y(0) - 1.8, "0")

    n = len(sylls)
    step = w / max(1, n)
    pts = [(x + step * (i + 0.5), to_y(v)) for i, (_, v) in enumerate(sylls)]
    c.setStrokeColor(bk.th.accent)
    c.setLineWidth(1.2)
    p = c.beginPath()
    p.moveTo(*pts[0])
    for pt in pts[1:]:
        p.lineTo(*pt)
    c.drawPath(p, stroke=1, fill=0)
    for (sx, sy), (txt, v) in zip(pts, sylls):
        c.setFillColor(bk.th.accent)
        c.circle(sx, sy, 1.5, stroke=0, fill=1)
        c.setFont(bk.th.ipa_font, 5.4)
        c.drawCentredString(sx, sy + (3.2 if v > 2 else -6.0), "%+.1f" % v)
        c.setFillColor(bk.th.ipa)
        c.setFont(bk.th.ipa_font, 6.4)
        c.drawCentredString(sx, y - 8, txt)
    c.setFillColor(bk.th.ink)
    c.setFont(bk.th.ipa_font, 7.6)
    c.drawCentredString(x + w / 2, y - 17, word)


def pitch_page(bk, examples, levels: list, practice: list):
    i18n = bk.i18n["chart"]
    bk.space(6)
    bk.mixed(T.ML, bk.y - 16, i18n["title"], size=15, color=bk.th.ink)
    bk.space(26)
    bk.mixed(T.ML, bk.y - 8, i18n["intro"], size=8.6, color=bk.th.grey)
    bk.space(26)

    x0, y0 = T.ML, bk.y
    bk.c.setFillColor(bk.th.grey)
    bk.c.setFont(bk.th.cjk_font, 7.4)
    bk.c.drawString(x0, y0, i18n["col_levels"])
    bk.c.drawString(x0 + 58, y0, i18n["col_meaning"])
    bk.c.drawString(x0 + 190, y0, i18n["col_example"])
    yy = y0 - 15
    for (lv, meaning), eg in zip(i18n["levels"], levels):
        bk.mixed(x0, yy, lv, size=7.8,
                 color=bk.th.accent if lv.startswith("+")
                 else (bk.th.ipa if lv.startswith("−") or lv.startswith("0")
                       else bk.th.grey))
        bk.mixed(x0 + 58, yy, meaning, size=7.6, color=bk.th.ink)
        bk.mixed(x0 + 190, yy, eg, size=7.2, color=bk.th.grey)
        yy -= 13
    bk.y = yy - 6

    bk.space(4)
    for t in i18n["tips"]:
        bk.mixed(T.ML, bk.y - 8, "· " + t, size=7.8, color=bk.th.grey)
        bk.space(12)

    bk.space(10)
    bk.mixed(T.ML, bk.y - 8, i18n["examples"], size=8.4, color=bk.th.ink)
    bk.space(16)
    cw = (T.CONTENT_W - 30) / 3
    for i, (word, sylls) in enumerate(examples[:3]):
        draw_chart(bk, T.ML + 16 + i * (cw + 12), bk.y - 84, cw - 24, 76, word, sylls)
    bk.y -= 114

    bk.space(10)
    bk.rule(6)
    bk.space(8)
    bk.mixed(T.ML, bk.y - 8, i18n["practice_title"], size=9, color=bk.th.ink)
    bk.space(14)
    for line in practice:
        bk.mixed(T.ML + 4, bk.y - 8, "· " + line, size=7.8, color=bk.th.grey)
        bk.space(12.5)


def map_page(bk, rows: list):
    i18n = bk.i18n["map"]
    bk.space(6)
    bk.mixed(T.ML, bk.y - 16, i18n["title"], size=15, color=bk.th.ink)
    bk.space(26)
    bk.mixed(T.ML, bk.y - 8, i18n["intro"], size=8.6, color=bk.th.grey)
    bk.space(24)
    y = bk.y
    bk.c.setStrokeColor(bk.th.rule)
    bk.c.setLineWidth(1.0)
    bk.c.line(T.ML + 52, y, T.ML + 52, y - 30 * len(rows) + 16)
    for year, what, why in rows:
        bk.c.setFillColor(bk.th.rule)
        bk.c.circle(T.ML + 52, y - 3, 1.8, stroke=0, fill=1)
        bk.c.setFillColor(bk.th.accent)
        bk.c.setFont(bk.th.ipa_font, 8)
        bk.c.drawRightString(T.ML + 42, y - 6, str(year))
        bk.mixed(T.ML + 62, y - 6, what, size=8.4, color=bk.th.ink)
        bk.mixed(T.ML + 62, y - 17, why, size=7.4, color=bk.th.grey)
        y -= 30
    bk.y = y


def legend(bk, rows=None):
    """符号表：左边画真实的标注样例，右边说明含义。"""
    i18n = bk.i18n["legend"]
    rows = rows or i18n["rows"]
    bk.mixed(T.ML, bk.y - 10, i18n["title"], size=9, color=bk.th.ink)
    bk.y -= 26
    for kind, sample, desc in rows:
        y = bk.y
        x = T.ML + 6
        if kind in ("ipa", "ipa2", "ipa3", "ipa4"):
            bk.c.setFillColor(bk.th.ipa)
            bk.c.setFont(bk.th.ipa_font, 8.4)
            bk.c.drawString(x, y, sample)
        elif kind == "acc":
            bk.c.setFillColor(bk.th.accent)
            bk.c.setFont(bk.th.ipa_font, T.MARK_SIZE)
            bk.c.drawCentredString(x + 2.6, y, "H")
            bk.draw_arrow(x + 8.4, y + 1.8, "↗")
        elif kind == "arrow":
            for k, c in enumerate(["↗", "↘", "→"]):
                bk.draw_arrow(x + 4 + k * 11, y + 2.0, c)
        elif kind == "num":
            bk.c.setFillColor(bk.th.lost)
            bk.c.setFont(bk.th.ipa_font, T.TINY_SIZE)
            bk.c.drawString(x, y, sample)
        elif kind == "weak":
            bk.c.setFillColor(bk.th.weak)
            bk.c.setFont(bk.th.ipa_font, T.TINY_SIZE)
            bk.c.drawString(x, y, "ʌ→ə")
        elif kind == "tie":
            bk.draw_tie(x, x + 13, y + 3)
        bk.mixed(T.ML + 74, y, desc, size=8, color=bk.th.grey)
        bk.y -= 15
