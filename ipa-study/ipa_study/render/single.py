# -*- coding: utf-8 -*-
"""单篇精读：短片（<12 分钟）用这个形态。

没有分章、没有全书地图、没有回忆问题 —— 一篇就是一篇。硬套分章版式
会得到一本只有一章、地图空一半的怪书。
"""
from __future__ import annotations

from . import charts
from . import content as K
from . import theme as T
from .base import Renderer
from .book import _cover, _paragraph


class SingleRenderer(Renderer):
    def __init__(self, path, theme, i18n, title):
        self.features = {}
        super().__init__(path, theme, i18n, title=title,
                         header_fn=lambda _p: title)


def build_single(job, units, s: dict, out_path):
    lang = job.render_cfg["content"].get("ui_lang", "zh")
    i18n = K.load_i18n(lang)
    theme = T.Theme.from_config(job.render_cfg["theme"], lang)
    feat = job.render_cfg["features"]
    i18n["cover"]["howto"] = i18n["cover"].get("howto_single",
                                               i18n["cover"]["howto"])

    bk = SingleRenderer(out_path, theme, i18n, job.title)
    bk.features = feat

    _cover(bk, job, s, i18n, feat)

    if feat.get("legend", True):
        bk.new_page()
        bk.space(6)
        bk.mixed(T.ML, bk.y - 16, i18n["symbols"]["title"], size=15, color=theme.ink)
        bk.space(26)
        charts.legend(bk, K.legend_rows(units, i18n))
        bk.space(8)
        bk.mixed(T.ML, bk.y - 8, i18n["symbols"]["caption"], size=7.8, color=theme.grey)

    if feat.get("pitch_page", True) and units:
        bk.new_page()
        charts.pitch_page(bk, K.pick_chart_examples(units),
                          K.level_examples(units), i18n["practice"])

    bk.new_page()
    for i, para in enumerate(units):
        _paragraph(bk, i, para)

    bk.save()
    return bk
