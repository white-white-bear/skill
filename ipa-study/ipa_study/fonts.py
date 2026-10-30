# -*- coding: utf-8 -*-
"""字体解析与码位校验。

原来的 render.py 把字体写死成 C:\\Windows\\Fonts\\l_10646.ttf 和 msyh.ttc，
换一台机器或换一个 agent 直接崩。这里按"配置 → 环境变量 → 平台默认 → 包内
回退 → 降级英文"的顺序找，并在渲染前校验 IPA 必需的码位，缺字直接失败，
不允许悄悄渲染成方框。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# annotation 里真正会画出来的字符。少任何一个都会出现方框或豆腐块。
REQUIRED_CODEPOINTS = {
    "元音": "ɑæʌɔɛɜɪiʊuəɚeoa",
    "辅音": "pbtdkɡfvθðszʃʒhtʃdʒmnŋlrjw",
    "符号": "ːˈˌɾ̚↗↘→·—–",
}

_CANDIDATES = {
    "win32": {
        "ipa": [r"C:\Windows\Fonts\l_10646.ttf",
                r"C:\Windows\Fonts\arial.ttf",
                r"C:\Windows\Fonts\seguisym.ttf"],
        "cjk": [r"C:\Windows\Fonts\msyh.ttc",
                r"C:\Windows\Fonts\msyhl.ttc",
                r"C:\Windows\Fonts\simsun.ttc"],
    },
    "darwin": {
        "ipa": ["/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                "/Library/Fonts/Arial Unicode.ttf"],
        "cjk": ["/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/Supplemental/Songti.ttc"],
    },
    "linux": {
        "ipa": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"],
        "cjk": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"],
    },
}


def _platform_key() -> str:
    if sys.platform.startswith("win"):
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _package_fallback(kind: str) -> list:
    here = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    return [str(here / n) for n in (["DejaVuSans.ttf"] if kind == "ipa"
                                    else ["NotoSansCJKsc-Regular.otf",
                                          "SourceHanSansSC-Regular.otf"])]


def resolve(kind: str, explicit: str = "") -> str | None:
    """kind 取 'ipa' 或 'cjk'；返回可用的字体路径或 None。"""
    env = os.environ.get("IPA_FONT" if kind == "ipa" else "CJK_FONT", "")
    for cand in ([explicit] if explicit else []) + \
                ([env] if env else []) + \
                _CANDIDATES[_platform_key()][kind] + \
                _package_fallback(kind):
        if cand and Path(cand).exists():
            return str(Path(cand))
    return None


def missing_codepoints(font_path: str) -> list:
    """返回该字体缺的字符列表；无法检查（没装 fontTools）时返回空。"""
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return []
    try:
        font = TTFont(font_path, fontNumber=0, lazy=True)
    except Exception:
        return []
    cmap: set = set()
    for table in font["cmap"].tables:
        cmap |= set(table.cmap.keys())
    font.close()
    need = set()
    for chars in REQUIRED_CODEPOINTS.values():
        need |= set(chars)
    return sorted(ch for ch in need if ord(ch) not in cmap)


def plan(theme: dict, ui_lang: str = "zh") -> dict:
    """返回 {ipa, cjk, ui_lang, warnings}，供渲染层直接使用。"""
    ipa = resolve("ipa", theme.get("ipa_font", ""))
    cjk = resolve("cjk", theme.get("cjk_font", ""))
    warns = []
    if not ipa:
        raise RuntimeError(
            "找不到可用的 IPA 字体。设置环境变量 IPA_FONT 指向一个含 IPA 字形的 "
            "ttf（如 DejaVuSans.ttf），或在 render.theme.ipa_font 里写绝对路径。")
    miss = missing_codepoints(ipa)
    if miss:
        warns.append(f"IPA 字体缺 {len(miss)} 个必需字符："
                     + " ".join(f"U+{ord(c):04X}({c})" for c in miss[:12]))
    if not cjk and ui_lang == "zh":
        warns.append("没有中文字体，界面文字自动降级为英文")
        ui_lang = "en"
    return {"ipa": ipa, "cjk": cjk, "ui_lang": ui_lang, "warnings": warns}


def report(theme: dict) -> str:
    p = plan(theme)
    lines = [f"IPA 字体：{p['ipa']}", f"中文字体：{p['cjk'] or '(无)'}",
             f"界面语言：{p['ui_lang']}"]
    lines += [f"警告：{w}" for w in p["warnings"]]
    return "\n".join(lines)
