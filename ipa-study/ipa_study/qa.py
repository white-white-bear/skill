# -*- coding: utf-8 -*-
"""验收：把"看起来像"变成"测得出"。

分两层：
- 数据层：标注计数、比例、覆盖率，与金标准 expected_metrics.json 比。
- 成品层：PDF 页数、缺字、每章首末词是否真的印出来了。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import stats as S

# 各比例的合理区间。
#
# 注意这里**没有** unrel（失爆）：它没法用一个固定区间判。失爆机会取决于
# 句子长短——一句一停的跟读材料里句末塞音占比能到 21%，连续旁白只有 3%。
# 用固定区间判，换一种素材就会误报（实测过一次：把正确的 6.4% 判成超标）。
# 失爆改为查"规则执行得一致不一致"，见 check_unreleased_coverage()。
RATIO_BANDS = {
    "weak": (0.15, 0.28),
    "link": (0.18, 0.32),
    "elide": (0.10, 0.19),
    "flap": (0.06, 0.13),
    "accent": (0.10, 0.25),
}

STOPS = {"P", "T", "K", "B", "D", "G"}


def _base(phone: str) -> str:
    return (phone or "")[:2] if (phone or "")[-1:].isdigit() else (phone or "")


def check_unreleased_coverage(units) -> list:
    """失爆的自洽检查：规则该触发的地方，是否真的都标了。

    机会数 = 词尾是塞音、且后面接辅音或位于句末。标注数 = 标了不除阻或吞音的。
    两者应当接近 100%——规则是确定性的，漏标说明音素序列或分句出了问题。
    这比"失爆应该占 6%"可靠，因为机会数是从素材本身算出来的。
    """
    opp = hit = 0
    for para in units:
        for sent in para["sents"]:
            ws = sent["words"]
            for k, w in enumerate(ws):
                ph = w.get("phones") or []
                if not ph or _base(ph[-1]) not in STOPS:
                    continue
                nxt = ws[k + 1]["phones"] if k + 1 < len(ws) else None
                next_vowel = bool(nxt) and _base(nxt[0]) in {
                    "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY",
                    "IH", "IY", "OW", "OY", "UH", "UW"}
                if nxt and next_vowel:
                    continue
                opp += 1
                if w.get("unreleased") or (len(ph) - 1) in (w.get("elided") or []):
                    hit += 1
    if opp < 20:
        return []
    cov = hit / opp
    if cov < 0.95:
        return [f"失爆规则只覆盖了 {cov:.0%} 的机会（{hit}/{opp}），"
                f"可能有音素序列或分句问题"]
    return []


def load_expected(path) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def compare_metrics(actual: dict, expected: dict,
                    exact_keys=("words", "sentences", "paragraphs"),
                    tol: dict | None = None) -> list:
    """返回差异列表；空列表即通过。"""
    tol = tol or {"accent": 0.02, "weak": 0.03, "link": 0.03,
                  "unreleased": 0.02, "elided": 0.03, "flapped": 0.02}
    diffs = []
    for k in exact_keys:
        if expected.get(k) is not None and actual.get(k) != expected[k]:
            diffs.append(f"{k}: 期望 {expected[k]}，实际 {actual.get(k)}")
    for k, t in tol.items():
        exp, act = expected.get(k), actual.get(k)
        if exp is None or act is None:
            continue
        denom = max(1, expected.get("words", 1))
        if abs(act - exp) / denom > t:
            diffs.append(f"{k}: 期望 {exp}，实际 {act}（差 {act - exp:+d}）")
    return diffs


def check_ratios(actual: dict) -> list:
    """没有金标准的新素材，用它判断比例是否健康。"""
    n = max(1, actual.get("words", 0))
    out = []
    for k, (lo, hi) in RATIO_BANDS.items():
        r = actual.get(k, 0) / n
        if not (lo <= r <= hi):
            out.append(f"{k} 比例 {r:.1%} 落在 [{lo:.0%}, {hi:.0%}] 之外")
    return out


def pdf_report(path) -> dict:
    """页数、字符数、缺字数（U+FFFD）。"""
    p = Path(path)
    if not p.exists():
        return {"exists": False}
    try:
        from pypdf import PdfReader
    except ImportError:
        return {"exists": True, "pages": None,
                "note": "未安装 pypdf，跳过 PDF 层检查"}
    r = PdfReader(str(p))
    text = "".join((pg.extract_text() or "") for pg in r.pages)
    return {
        "exists": True,
        "pages": len(r.pages),
        "chars": len(text),
        "missing_glyphs": text.count("�"),
        "_text": text,
    }


def check_pdf(path, job, units_by_chapter: dict) -> list:
    rep = pdf_report(path)
    if not rep.get("exists"):
        return [f"PDF 不存在：{path}"]
    out = []
    if rep.get("missing_glyphs"):
        out.append(f"PDF 里有 {rep['missing_glyphs']} 个缺字符号（字体缺字）")
    text = rep.get("_text")
    if text is None:
        return out
    for ch in job.chapters:
        units = units_by_chapter.get(ch.id)
        if not units:
            continue
        first = units[0]["sents"][0]["words"][0]["surface"]
        last = units[-1]["sents"][-1]["words"][-1]["surface"]
        if first not in text:
            out.append(f"第 {ch.id} 章首词 {first!r} 没有出现在 PDF 里")
        if last not in text:
            out.append(f"第 {ch.id} 章末词 {last!r} 没有出现在 PDF 里")
    return out


def run(job, units_by_chapter: dict, pdf_path=None) -> dict:
    actual = {}
    for units in units_by_chapter.values():
        for k, v in S.count(units).items():
            actual[k] = actual.get(k, 0) + v

    expected = load_expected(job.root / "expected_metrics.json")
    report = {
        "counts": actual,
        "ratios": S.ratios(actual),
        "problems": [],
        "baseline": "examples/steve-jobs/expected_metrics.json" if expected else None,
    }
    if expected:
        report["problems"] += compare_metrics(actual, expected)
    else:
        report["problems"] += check_ratios(actual)
    for units in units_by_chapter.values():
        report["problems"] += check_unreleased_coverage(units)
    if pdf_path:
        report["pdf"] = {k: v for k, v in pdf_report(pdf_path).items()
                         if not k.startswith("_")}
        report["problems"] += check_pdf(pdf_path, job, units_by_chapter)
    return report
