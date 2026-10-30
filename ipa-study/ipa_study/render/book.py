# -*- coding: utf-8 -*-
"""分章全书：封面 → 全书地图 → 音高查询表 → 符号表 → 各章正文。

章节列表来自 job.chapters，不再有 range(1, 13) 或者 f"ch{n:02d}" 的假设。
"""
from __future__ import annotations

from . import charts
from . import content as K
from . import theme as T
from .base import Renderer


class BookRenderer(Renderer):
    def __init__(self, path, theme, i18n, title):
        self.book_title = title
        self.chapter_label = ""
        super().__init__(path, theme, i18n, title=title,
                         header_fn=lambda _p: self.header_line())

    def header_line(self) -> str:
        parts = [self.book_title]
        if self.chapter_label:
            parts.append(self.chapter_label)
        return "｜".join(p for p in parts if p)

    # ------------------------------------------------------------ 章节开头
    def chapter_open(self, n: int, meta, n_sent: int, is_section: bool):
        i18n = self.i18n["chapter"]
        self.chapter_label = (i18n["section_label"] if is_section
                              else i18n["label"]).format(n=n)
        self.ensure(150)
        self.space(6)
        self.mixed(T.ML, self.y - 16, self.chapter_label, size=9, color=self.th.grey)
        self.space(20)
        self.mixed(T.ML, self.y - 18, meta.title, size=16, color=self.th.ink)
        self.space(26)
        self.mixed(T.ML, self.y - 8,
                   i18n["open_span"].format(span=meta.span_text, n=n_sent),
                   size=8, color=self.th.grey)
        self.space(16)
        if meta.carry:
            self.mixed(T.ML, self.y - 8, meta.carry, size=9, color=self.th.ipa)
            self.space(13)
        if meta.keys:
            self.mixed(T.ML, self.y - 8, i18n["keywords"].format(keys=meta.keys),
                       size=8, color=self.th.grey)
            self.space(14)
        self.rule(5)

    # ------------------------------------------------------------ 章节收尾
    def chapter_end(self, meta, next_title, show_questions: bool):
        i18n = self.i18n["chapter"]
        if show_questions and meta.ask:
            self.ensure(96)
            self.space(6)
            self.c.setFillColor(self.th.rule)
            box_h = 18 + 13 * len(meta.ask)
            self.c.setFillColorRGB(0.969, 0.961, 0.949)
            self.c.rect(T.ML, self.y - box_h, T.CONTENT_W, box_h, stroke=0, fill=1)
            yy = self.y - 13
            self.mixed(T.ML + 9, yy, i18n["ask_head"], size=7.6, color=self.th.grey)
            for i, q in enumerate(meta.ask):
                yy -= 12.5
                self.mixed(T.ML + 9, yy, f"{i + 1}. {q}", size=8, color=self.th.ipa)
            self.y -= box_h + 8
        if next_title:
            self.mixed(T.ML, self.y - 8, i18n["next"].format(title=next_title),
                       size=8, color=self.th.grey)
            self.space(12)
        self.chapter_label = ""


def build_book(job, units_by_chapter: dict, s: dict, out_path, only=None):
    """units_by_chapter: {章号: units}；s 是 stats.doc_stats 的结果。

    only 给定时只排这几章（出样张用），不改变数据，只改变印哪些页。
    """
    lang = job.render_cfg["content"].get("ui_lang", "zh")
    i18n = K.load_i18n(lang)
    theme = T.Theme.from_config(job.render_cfg["theme"], lang)
    feat = job.render_cfg["features"]
    title = job.title

    bk = BookRenderer(out_path, theme, i18n, title)
    bk.features = feat
    chapters = [c for c in job.chapters if only is None or c.id in only]
    if not chapters:
        raise ValueError("没有可排的章节")
    first_units = units_by_chapter.get(chapters[0].id, [])

    _cover(bk, job, s, i18n, feat)

    if feat.get("map") and job.raw["render"]["content"].get("map_rows"):
        bk.new_page()
        charts.map_page(bk, job.raw["render"]["content"]["map_rows"])

    if feat.get("pitch_page") and first_units:
        bk.new_page()
        charts.pitch_page(bk, K.pick_chart_examples(first_units),
                          K.level_examples(first_units), i18n["practice"])

    if feat.get("legend"):
        bk.new_page()
        bk.space(6)
        bk.mixed(T.ML, bk.y - 16, i18n["symbols"]["title"], size=15, color=theme.ink)
        bk.space(26)
        charts.legend(bk, K.legend_rows(first_units, i18n))
        bk.space(8)
        bk.mixed(T.ML, bk.y - 8, i18n["symbols"]["caption"], size=7.8, color=theme.grey)

    is_section = job.form["kind"] == "sections"
    for k, ch in enumerate(chapters):
        units = units_by_chapter.get(ch.id)
        if units is None:
            continue
        bk.new_page()
        n_sent = sum(len(p["sents"]) for p in units)
        bk.chapter_open(ch.id, ch, n_sent, is_section)
        bk.space(26)
        for i, para in enumerate(units):
            _paragraph(bk, i, para)
        nxt = chapters[k + 1].title if k + 1 < len(chapters) else ""
        bk.chapter_end(ch, nxt, feat.get("chapter_questions", True))

    bk.save()
    return bk


def _paragraph(bk, i, para):
    i18n = bk.i18n
    bk.ensure(130)
    bk.space(4)
    bk.mixed(T.ML, bk.y - 8, i18n["para"]["label"].format(n=i + 1),
             size=9, color=bk.th.grey)
    bk.space(12)
    first, last = para["sents"][0]["words"][0], para["sents"][-1]["words"][-1]
    bk.cjk(i18n["para"]["time"].format(
        a=f"{first['start']:.0f}", b=f"{last['end']:.0f}",
        n=len(para["sents"])), 7.4, bk.th.grey)
    bk.space(32)                     # 给第一句的重音/音节音高留足空间
    for j, sent in enumerate(para["sents"]):
        bk.sentence(f"{j + 1}.", sent["words"])
        bk.space(13)
    if getattr(bk, "features", {}).get("summary", True):
        bk.summary(para)


def _cover(bk, job, s, i18n, feat):
    th = bk.th
    c = bk.c
    is_section = job.form["kind"] == "sections"
    c.setFillColor(th.ink)
    c.setFont(th.ipa_font, 9)
    c.drawString(T.ML, T.PAGE_H - 34 * T.MM, (job.project.get("title_en") or "").upper())
    c.setFont(th.cjk_font, 24)
    c.drawString(T.ML, T.PAGE_H - 47 * T.MM, job.project.get("title_zh") or job.title)
    c.setFont(th.cjk_font, 10)
    c.setFillColor(th.grey)
    c.drawString(T.ML, T.PAGE_H - 58 * T.MM, i18n["cover"]["tagline"])
    c.setFont(th.cjk_font, 8.6)
    unit = "节" if is_section else "章"
    c.drawString(T.ML, T.PAGE_H - 68 * T.MM,
                 f"{s['chapters']} {unit} · {s['sentences']} 句 · {s['duration_text']}")

    bk.y = T.PAGE_H - 84 * T.MM
    bk.mixed(T.ML, bk.y, i18n["cover"]["howto_title"], size=11, color=th.ink)
    bk.space(12)
    # 没有地图页时不能让人"先读全书地图"——分节形态通常没有地图
    has_map = bool(feat.get("map")) and bool(
        job.raw["render"]["content"].get("map_rows"))
    howto = i18n["cover"]["howto"] if has_map else \
        i18n["cover"].get("howto_sections", i18n["cover"]["howto"])
    for line in howto:
        bk.mixed(T.ML, bk.y - 8, line, size=8.4, color=th.grey)
        bk.space(13)
    bk.space(10)
    bk.rule(6)
    bk.space(8)
    bk.mixed(T.ML, bk.y - 8, i18n["methods"]["title"], size=9, color=th.ink)
    bk.space(14)
    for line in K.methods_lines(s, "zh" if bk.th.cjk_ok else "en"):
        bk.cjk(line, 7.6, th.grey, leading=11.5, indent=4)
        bk.space(2)
