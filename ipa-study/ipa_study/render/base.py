# -*- coding: utf-8 -*-
"""行间注排版引擎。

这一层只管"怎么画"，不知道画的是谁的书。书名、页眉、文案都从构造参数进来。
原来写死在 Renderer.__init__ 和 draw_header 里的 "Steve Jobs 发音精读版 v3.0"
就是这样一点点漏进引擎的。
"""
from __future__ import annotations

import re

from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import Paragraph

from ..lexicon import to_ipa
from . import theme as T


def is_cjk(ch: str) -> bool:
    o = ord(ch)
    return o >= 0x2E80


def _runs(text: str):
    out, cur, cur_cjk = [], "", None
    for ch in text:
        c = is_cjk(ch)
        if cur and c != cur_cjk:
            out.append((cur, cur_cjk))
            cur = ""
        cur += ch
        cur_cjk = c
    if cur:
        out.append((cur, cur_cjk))
    return out


def w_of(text: str, font: str, size: float) -> float:
    try:
        return pdfmetrics.stringWidth(text, font, size)
    except Exception:
        return len(text) * size * 0.5


class Renderer:
    """页面骨架 + 行间注绘制。子类负责页面顺序与内容。"""

    def __init__(self, path, theme: T.Theme, i18n: dict, title: str = "",
                 header_fn=None):
        self.th = theme
        self.i18n = i18n
        self.title = title
        self.header_fn = header_fn
        self.c = pdfcanvas.Canvas(str(path), pagesize=(T.PAGE_W, T.PAGE_H))
        self.c.setTitle(title)
        self.page = 0
        self.y = T.PAGE_H - T.MT
        self.new_page(first=True)

    # ---------------------------------------------------------------- 页面骨架
    def new_page(self, first: bool = False):
        if not first:
            self.c.showPage()
        self.page += 1
        # 页眉与正文之间要给音高、重音标记留出至少一行的空间
        self.y = T.PAGE_H - T.MT - 30
        self.draw_header()

    def header_text(self) -> str:
        return self.header_fn(self.page) if self.header_fn else self.title

    def draw_header(self):
        self.c.setFillColor(self.th.grey)
        self.c.setFont(self.th.cjk_font, 7.2)
        self.c.drawString(T.ML, T.PAGE_H - 12 * T.MM, self.header_text())
        self.c.setFont(self.th.ipa_font, 7.2)
        self.c.drawRightString(T.PAGE_W - T.MR, T.PAGE_H - 12 * T.MM, str(self.page))
        self.c.setStrokeColor(self.th.rule)
        self.c.setLineWidth(0.4)
        self.c.line(T.ML, T.PAGE_H - 14 * T.MM, T.PAGE_W - T.MR, T.PAGE_H - 14 * T.MM)

    # ---------------------------------------------------------------- 基础原语
    def mixed_width(self, text: str, size: float) -> float:
        return sum(w_of(run, self.th.cjk_font if cjk else self.th.ipa_font, size)
                   for run, cjk in _runs(text))

    def mixed(self, x, y, text, size=8, color=None, align="left"):
        """中英混排：按字符类别切换字体，逐段绘制。"""
        color = color or self.th.ink
        total = self.mixed_width(text, size)
        if align == "center":
            x -= total / 2
        elif align == "right":
            x -= total
        self.c.setFillColor(color)
        for run, cjk in _runs(text):
            font = self.th.cjk_font if cjk else self.th.ipa_font
            self.c.setFont(font, size)
            self.c.drawString(x, y, run)
            x += w_of(run, font, size)
        return total

    def space(self, h):
        self.y -= h

    def ensure(self, h):
        if self.y - h < T.MB:
            self.new_page()

    def cjk(self, text, size=9.2, color=None, leading=None, indent=0, width=None):
        color = color or self.th.ink
        width = width or T.CONTENT_W - indent
        st = ParagraphStyle("s", fontName=self.th.cjk_font, fontSize=size,
                            leading=leading or size * 1.62, textColor=color,
                            wordWrap="CJK", spaceAfter=0, spaceBefore=0)
        p = Paragraph(self.escape(text), st)
        w, h = p.wrap(width, 10000)
        self.ensure(h)
        p.drawOn(self.c, T.ML + indent, self.y - h)
        self.y -= h

    @staticmethod
    def escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def rule(self, gap=6):
        self.y -= gap
        self.c.setStrokeColor(self.th.rule)
        self.c.setLineWidth(0.5)
        self.c.line(T.ML, self.y, T.PAGE_W - T.MR, self.y)
        self.y -= gap

    # ---------------------------------------------------------------- 行间注
    def sentence(self, num, words):
        cells = []
        for w in words:
            en = w.get("lead", "") + w["surface"] + w.get("punct", "")
            ipa = w["ipa"]
            en_w = w_of(en, self.th.ipa_font, T.EN_SIZE)
            # 音标比英文词宽太多时（1976 → nineteen seventy-six）压小字号，
            # 否则一个数字词会撑开整行的列宽
            size = T.IPA_SIZE
            if w_of(ipa, self.th.ipa_font, T.IPA_SIZE) > max(en_w * 1.7, 34):
                size = max(5.6, T.IPA_SIZE * max(en_w * 1.7, 34)
                           / w_of(ipa, self.th.ipa_font, T.IPA_SIZE))
            cw = max(en_w, w_of(ipa, self.th.ipa_font, size)) + 5.6
            cells.append((w, en, ipa, cw, size))

        lines, cur, used = [], [], 0.0
        for cell in cells:
            if used + cell[3] > T.CONTENT_W - 22 and cur:
                lines.append(cur)
                cur, used = [], 0.0
            cur.append(cell)
            used += cell[3]
        if cur:
            lines.append(cur)

        need = T.LEAD * len(lines) + 6
        self.ensure(need)
        for li, line in enumerate(lines):
            self.draw_line(line, num if li == 0 else None)
            self.y -= T.LEAD
        self.y -= 4

    def draw_line(self, cells, num):
        x = T.ML + 24
        if num is not None:
            self.c.setFillColor(self.th.grey)
            self.c.setFont(self.th.ipa_font, 7.5)
            self.c.drawString(T.ML, self.y + 1, num)
        base = self.y
        prev = None
        prev_ipa_right = prev_en_right = x
        for w, en, ipa, cw, isize in cells:
            # 连字符复合词（Hewlett-Packard）左右各自成列，把间距收掉
            if prev is not None and prev.get("punct", "").endswith("-"):
                x -= 2.6
            cx = x + cw / 2
            ipa_left = cx - w_of(ipa, self.th.ipa_font, isize) / 2
            en_left = cx - w_of(en, self.th.ipa_font, T.EN_SIZE) / 2
            if prev is not None and prev.get("link"):
                # 优先画在两个英文词之间的空白里，那里没有字形遮挡
                if en_left - prev_en_right > 2.2:
                    self.draw_tie(prev_en_right, en_left, base - 3.0)
                elif ipa_left - prev_ipa_right > 2.2:
                    self.draw_tie(prev_ipa_right, ipa_left, base + 5.4)
            self.c.setFillColor(self.th.ink)
            self.c.setFont(self.th.ipa_font, T.EN_SIZE)
            self.c.drawCentredString(cx, base, en)

            col = (self.th.accent if w["accent"]
                   else (self.th.weak if w.get("weak") else self.th.ipa))
            self.c.setFillColor(col)
            self.c.setFont(self.th.ipa_font, isize)
            self.c.drawCentredString(cx, base + T.OFF_IPA, ipa)

            if w["accent"]:
                self.c.setFillColor(self.th.accent)
                self.c.setFont(self.th.ipa_font, T.MARK_SIZE)
                self.c.drawCentredString(cx - 2.6, base + T.OFF_ACC, w["level"])
                self.draw_arrow(cx + 3.4, base + T.OFF_ACC + 1.8, w["contour"])
                self.draw_syll_pitch(w, x, cw, base + T.OFF_SYLL, isize)

            if w.get("weak") and w["weak"].get("vowel"):
                self.c.setFillColor(self.th.weak)
                self.c.setFont(self.th.ipa_font, T.TINY_SIZE)
                self.c.drawCentredString(cx, base + T.OFF_WEAK, w["weak"]["vowel"])

            prev_ipa_right = cx + w_of(ipa, self.th.ipa_font, isize) / 2
            prev_en_right = cx + w_of(en, self.th.ipa_font, T.EN_SIZE) / 2
            prev = w
            x += cw

    def draw_arrow(self, x, y, contour):
        """音高走向用矢量画，避免不同字体里箭头字形不一致。"""
        self.c.setStrokeColor(self.th.accent)
        self.c.setLineWidth(0.7)
        h = 2.0
        if contour == "↗":
            self.c.line(x - 2.4, y - h, x + 2.4, y + h)
            self.c.line(x + 2.4, y + h, x + 2.4, y + h - 2.2)
            self.c.line(x + 2.4, y + h, x + 2.4 - 2.2, y + h)
        elif contour == "↘":
            self.c.line(x - 2.4, y + h, x + 2.4, y - h)
            self.c.line(x + 2.4, y - h, x + 2.4, y - h + 2.2)
            self.c.line(x + 2.4, y - h, x + 2.4 - 2.2, y - h)
        else:
            self.c.line(x - 2.4, y, x + 2.4, y)
            self.c.line(x + 2.4, y, x + 2.4 - 1.8, y + 1.4)
            self.c.line(x + 2.4, y, x + 2.4 - 1.8, y - 1.4)

    def draw_syll_pitch(self, w, x, cw, y, isize=T.IPA_SIZE):
        """重读词内部每个音节的相对音高（半音，相对句内中位）。"""
        sylls = w["sylls"]
        if not sylls or len(sylls) < 2:      # 单音节词已在 H/M/L 里体现
            return
        vals = [s.get("st") for s in sylls]
        if all(v is None for v in vals):
            return
        ipa_w = w_of(w["ipa"], self.th.ipa_font, isize)
        left = x + cw / 2 - ipa_w / 2
        texts = [to_ipa(s["phones"])[0] for s in sylls]
        widths = [w_of(t, self.th.ipa_font, isize) for t in texts]
        tot = sum(widths) or 1
        cx = left
        self.c.setFillColor(self.th.lost)
        self.c.setFont(self.th.ipa_font, T.TINY_SIZE)
        for t, wd, v in zip(texts, widths, vals):
            if v is not None:
                self.c.drawCentredString(cx + wd / 2, y,
                                         ("%+.0f" % v).replace("+0", "0"))
            cx += wd * ipa_w / tot

    def draw_tie(self, x1, x2, y):
        """连读：在相邻两词的空隙里画一道下弯的连音线。"""
        self.c.setStrokeColor(self.th.link)
        self.c.setLineWidth(0.7)
        x1, x2 = x1 - 1.0, x2 + 1.0
        if x2 - x1 < 3:
            return
        mid = (x1 + x2) / 2
        path = self.c.beginPath()
        path.moveTo(x1, y + 2.0)
        path.curveTo(mid, y - 2.6, mid, y - 2.6, x2, y + 2.0)
        self.c.drawPath(path, stroke=1, fill=0)

    # ---------------------------------------------------------------- 段落小结
    def summary(self, para):
        ws = [w for s in para["sents"] for w in s["words"]]
        cnt = dict(
            weak=sum(1 for w in ws if w.get("weak")),
            link=sum(1 for w in ws if w.get("link")),
            unrel=sum(1 for w in ws if w.get("unreleased")),
            elide=sum(1 for w in ws if w.get("elided")),
            flap=sum(1 for w in ws if w.get("flapped")),
        )
        s = self.i18n["summary"]
        head = s["head"].format(**cnt)
        ex = self.example_lines(para)
        box_h = 16 + 11 * len(ex) + 6
        self.ensure(box_h + 14)
        self.y -= 6
        self.c.setFillColor(HexColor("#f4f6f8"))
        self.c.rect(T.ML, self.y - box_h, T.CONTENT_W, box_h, stroke=0, fill=1)
        x = T.ML + 9
        self.mixed(x, self.y - 13, head, size=7.6, color=self.th.grey)
        yy = self.y - 13
        for line in ex:
            yy -= 11
            self.mixed(x, yy, line, size=7.4, color=self.th.ipa)
        self.y -= box_h + 8

    def example_lines(self, para):
        ws = [w for s in para["sents"] for w in s["words"]]
        s = self.i18n["summary"]
        out = []
        weaks = [w for w in ws if w.get("weak")][:3]
        if weaks:
            out.append(s["weak"] + " · ".join(
                s["cite"].format(word=w["surface"], cite=w["weak"]["cite"],
                                 weak=w["weak"]["weak"]) for w in weaks))
        flaps = [w for w in ws if w.get("flapped")][:3]
        if flaps:
            out.append(s["flap"] + " · ".join(w["ipa"] for w in flaps))
        losts = [w for w in ws if w.get("elided") or w.get("unreleased")][:6]
        if losts:
            out.append(s["lost"] + " · ".join(w["ipa"] for w in losts))
        return out[:2]

    def save(self):
        self.c.showPage()
        self.c.save()
