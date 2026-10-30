# -*- coding: utf-8 -*-
"""视觉令牌：颜色、字号、分页尺寸、字体注册。

版式参数（行间注四层偏移、列宽、页边距）是为这一套标注调的，跨素材通用，
所以留成常量；颜色和字体可以按项目覆盖。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from .. import fonts as fontmod

# 版面（A4）
PAGE_W, PAGE_H = A4
MM = 2.834645
ML = MR = 17 * MM          # 左右 17mm
MT, MB = 19 * MM, 16 * MM  # 上下边距
CONTENT_W = PAGE_W - ML - MR

# 行间注四层
EN_SIZE, IPA_SIZE, MARK_SIZE, TINY_SIZE = 10.0, 8.0, 6.6, 5.6
LEAD = 36.0
OFF_IPA, OFF_SYLL, OFF_ACC, OFF_WEAK = 10.0, 17.0, 24.5, -8.0

_REGISTERED: dict = {}


def register_font(name_hint: str, path: str, subfont: int = 0) -> str:
    """同一个字体文件只注册一次；名字带上路径哈希，避免多项目互相覆盖。"""
    if path in _REGISTERED:
        return _REGISTERED[path]
    tag = hashlib.sha256(path.encode("utf-8")).hexdigest()[:6]
    name = f"{name_hint}-{tag}"
    if subfont:
        pdfmetrics.registerFont(TTFont(name, path, subfontIndex=subfont))
    else:
        pdfmetrics.registerFont(TTFont(name, path))
    _REGISTERED[path] = name
    return name


@dataclass
class Theme:
    ipa_font: str
    cjk_font: str
    ui_lang: str = "zh"
    ink: object = field(default_factory=lambda: HexColor("#1a1a1a"))
    grey: object = field(default_factory=lambda: HexColor("#6b7280"))
    ipa: object = field(default_factory=lambda: HexColor("#37474f"))
    accent: object = field(default_factory=lambda: HexColor("#c62828"))
    weak: object = field(default_factory=lambda: HexColor("#1565c0"))
    link: object = field(default_factory=lambda: HexColor("#00796b"))
    lost: object = field(default_factory=lambda: HexColor("#8d6e63"))
    rule: object = field(default_factory=lambda: HexColor("#d9d9d9"))
    paper: object = field(default_factory=lambda: HexColor("#ffffff"))
    warnings: list = field(default_factory=list)

    @classmethod
    def from_config(cls, cfg: dict, ui_lang: str = "zh") -> "Theme":
        plan = fontmod.plan(cfg, ui_lang)
        theme = cls(
            ipa_font=register_font("IPA", plan["ipa"]),
            cjk_font=(register_font("CJK", plan["cjk"], subfont=1)
                      if plan["cjk"] else register_font("IPA", plan["ipa"])),
            ui_lang=plan["ui_lang"],
            warnings=plan["warnings"],
        )
        for key, attr in (("accent_color", "accent"), ("weak_color", "weak"),
                          ("link_color", "link")):
            if cfg.get(key):
                setattr(theme, attr, HexColor(cfg[key]))
        return theme

    # 没有中文字体时退回 IPA 字体，至少不崩
    @property
    def cjk_ok(self) -> bool:
        return self.ui_lang == "zh"
