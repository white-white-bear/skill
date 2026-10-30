# -*- coding: utf-8 -*-
"""可编辑文案：图例、练习说明、音高表、方法说明、示例词。

这里的一切都会出现在成品里，但都不该写死在版式代码中。示例词尤其要
从当前素材的真实数据里挑 —— 照抄上一本书的 "Wozniak" 是最典型的空心化。
"""
from __future__ import annotations

import json
from pathlib import Path

I18N_DIR = Path(__file__).resolve().parent / "i18n"


def load_i18n(lang: str = "zh") -> dict:
    path = I18N_DIR / f"{lang}.json"
    if not path.exists():
        path = I18N_DIR / "en.json"
    return json.loads(path.read_text(encoding="utf-8"))


# 方法说明模板。{...} 里的数字全部由 stats 现算。
METHOD_TEMPLATES = {
    "zh": [
        "音频：{audio_name}（{duration_text}），共 {chapters} {unit}、{sentences} 句、{words} 词。",
        "对齐：{model} 产生词级时间戳，与正文逐词对齐，{words} 词中 {matched} 个直接命中。",
        "音高：Praat 基频追踪（75–400 Hz，步长 10 ms）；整段浊音中位 {baseline} Hz 作为"
        "说话人基线，H / M / L 与音节半音差都相对句内中位计算。",
        "强读：句内时长、峰值响度、基频顶点三项加权打分，超过阈值判为强读（全书 {accent} 词），"
        "与音高高低分开记录。",
        "弱读、连读、失爆、吞音、浊化：按美式音系规则在音素序列上判定，按音素位置逐个标注。",
        "已知限制：音节内配时优先取浊音段，段数与音节数不符时按音素数比例摊分；"
        "未对齐到时间戳的词由相邻词插值，且不参与重读判定。",
    ],
    "en": [
        "Audio: {audio_name} ({duration_text}), {chapters} {unit}, {sentences} sentences, {words} words.",
        "Alignment: {model} word-level timestamps aligned to the text; {matched} of {words} words matched directly.",
        "Pitch: Praat F0 tracking (75–400 Hz, 10 ms step); speaker baseline {baseline} Hz, the median of "
        "all voiced frames. H / M / L and syllable semitones are relative to the sentence median.",
        "Prominence: within-sentence duration, peak intensity and F0 peak, weighted; above threshold "
        "counts as prominent ({accent} words in total), recorded separately from pitch height.",
        "Reduction, linking, unreleased stops, elision and flapping follow American English "
        "phonological rules applied per phone position.",
        "Known limits: syllable timing prefers voiced runs; when the count disagrees it is distributed "
        "by phone count. Words without a timestamp are interpolated and never judged prominent.",
    ],
}


def _num(v) -> str:
    return f"{v:,}" if isinstance(v, int) else str(v)


def methods_lines(s: dict, lang: str = "zh") -> list:
    tpl = METHOD_TEMPLATES.get(lang, METHOD_TEMPLATES["en"])
    vals = {k: s.get(k, "") for k in
            ("audio_name", "duration_text", "chapters", "sentences", "words",
             "matched", "model", "baseline", "accent")}
    for k in ("chapters", "sentences", "words", "matched", "accent"):
        vals[k] = _num(vals[k])
    vals["baseline"] = f"{s.get('baseline_f0', 0):.1f}"
    vals.setdefault("unit", "节" if s.get("kind") == "sections" else "章")
    return [t.format(**vals) for t in tpl]


# ---------------------------------------------------------------- 示例挑选

def pick_chart_examples(units, n: int = 3) -> list:
    """挑 n 个重读的多音节词，尽量覆盖升 / 降 / 平三种走向。"""
    cands = []
    for p in units:
        for s in p.get("sents", []):
            for w in s["words"]:
                if not w.get("accent") or len(w.get("sylls", [])) < 2:
                    continue
                sylls = [(("".join(x.get("ipa", []))) or "?",
                          float(x.get("st") or 0.0)) for x in w["sylls"]]
                if not any(sy[1] for sy in sylls):
                    continue
                cands.append((w["surface"], w.get("contour", "→"), sylls))
    if not cands:
        return []
    picked, seen = [], set()
    for want in ("↗", "↘", "→"):
        for word, contour, sylls in cands:
            if contour == want and word.lower() not in seen:
                picked.append((word, sylls))
                seen.add(word.lower())
                break
    for word, _, sylls in cands:
        if len(picked) >= n:
            break
        if word.lower() not in seen:
            picked.append((word, sylls))
            seen.add(word.lower())
    return picked[:n]


def level_examples(units) -> list:
    """给音高表的 8 个档位各配一个真实例子，找不到就留空。"""
    bands = [(9, 99), (5, 7), (3, 4), (1, 2), (-0.5, 0.5),
             (-2, -1), (-5, -3), (-99, -6)]
    pool = []
    for p in units:
        for s in p.get("sents", []):
            for w in s["words"]:
                for sy in w.get("sylls", []):
                    st = sy.get("st")
                    if st is None:
                        continue
                    txt = "".join(sy.get("ipa", [])) or "?"
                    pool.append((float(st), w["surface"], txt))
    out = []
    for lo, hi in bands:
        hit = next(((v, word, txt) for v, word, txt in pool
                    if lo <= v <= hi and txt), None)
        out.append(f"{hit[1]}  {hit[2]} {hit[0]:+.1f}" if hit else "")
    return out


def legend_rows(units, i18n: dict) -> list:
    """把图例里那条 IPA 样例换成当前素材里的真实重读词，其余照模板。"""
    rows = [list(r) for r in i18n["legend"]["rows"]]
    ex = pick_chart_examples(units, 1)
    if ex:
        word = ex[0][0]
        real = next((w["ipa"] for p in units for s in p["sents"]
                     for w in s["words"]
                     if w["surface"] == word and w.get("accent")), None)
        if real:
            for r in rows:
                if r[0] == "ipa":
                    r[1] = real
    return rows
