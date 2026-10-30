# -*- coding: utf-8 -*-
"""回归测试。既可以 pytest 跑，也可以直接 `python tests/test_golden.py`。

金标准测试依赖旧的 steve-jobs-ipa 项目目录；找不到就跳过，不会失败。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ipa_study import config as CFG          # noqa: E402
from ipa_study import tokenize as TK         # noqa: E402
from ipa_study import align as AL            # noqa: E402
from ipa_study import chapterize as CZ       # noqa: E402

LEGACY = Path(r"F:\workspace\steve-jobs-ipa")


# ---------------------------------------------------------------- 记号化

def test_tokenize_punct_roundtrip():
    toks = TK.tokenize_punct('He said, "hello" to Wozniak.')
    words = [t[1] for t in toks]
    assert words == ["He", "said", "hello", "to", "Wozniak"]
    rebuilt = "".join(lead + w + tail for lead, w, tail in toks)
    assert rebuilt.replace(" ", "") == 'Hesaid,"hello"toWozniak.'


def test_tokenize_keeps_apostrophes():
    assert TK.tokenize("didn't stop") == ["didn't", "stop"]
    assert TK.norm("Wozniak's") == "wozniaks"


# ---------------------------------------------------------------- 对齐

def test_align_identity_maps_one_to_one():
    a = ["a", "b", "c", "d"]
    pairs = TK.align_seq(a, a)
    assert pairs == [(0, 0), (1, 1), (2, 2), (3, 3)]


def test_align_banded_survives_shift():
    """中间多一个词后，后面的词仍然要配上 —— 逐位比对会在这里全错。"""
    a = ["the", "cat", "sat", "on", "the", "mat"]
    b = ["the", "cat", "really", "sat", "on", "the", "mat"]
    pairs = TK.align_seq(a, b, band=4)
    matched = {i: j for i, j in pairs if j is not None}
    assert matched[4] == 5 and matched[5] == 6


def test_precheck_prefers_identity_for_same_text():
    words = [{"w": w, "start": i * 0.5, "end": i * 0.5 + 0.4}
             for i, w in enumerate("the cat sat on the mat".split())]
    d = AL.precheck([w["w"] for w in words], words)
    assert d["mode"] == "identity"


def test_precheck_detects_positional_drift():
    """正文和转写错开几个词时，逐位得分会崩，但匹配率仍然很高。"""
    text = "one two three four five six seven eight".split()
    words = [{"w": w, "start": i * 0.5, "end": i * 0.5 + 0.4}
             for i, w in enumerate("zero zero one two three four five six seven eight".split())]
    d = AL.precheck(text, words)
    assert d["mode"] in ("banded", "windowed_nw")
    assert d["match"] >= 0.6


# ---------------------------------------------------------------- 配置

def test_config_rejects_overlapping_chapters():
    job = CFG.Job.new(Path(tempfile.gettempdir()) / "x.json",
                      audio={"duration": 100.0})
    job.raw["chapters"] = [
        {"id": 1, "title": "a", "start": 0.0, "end": 60.0},
        {"id": 2, "title": "b", "start": 40.0, "end": 100.0},
    ]
    errs = job.validate()
    assert any("重叠" in e for e in errs)


def test_format_time():
    assert CFG.format_time(293.3) == "04:53"
    assert CFG.format_time(3963.9) == "1:06:04"
    assert CFG.format_time(0) == "00:00"


# ---------------------------------------------------------------- 分章

def test_form_for_duration():
    assert CZ.form_for(5 * 60)["kind"] == "single"
    assert CZ.form_for(30 * 60)["kind"] == "sections"
    assert CZ.form_for(68 * 60) == {"kind": "book", "k": 12}
    assert 8 <= CZ.form_for(180 * 60)["k"] <= 14


def test_candidates_exclude_edges():
    words = [{"w": f"w{i}", "start": i * 1.0, "end": i * 1.0 + 0.5}
             for i in range(100)]
    cands = CZ.candidates(words, {"candidate_gap_sec": 0.5,
                                  "edge_margin_sec": 30}, 100.0)
    assert all(30 <= c["time"] <= 70 for c in cands)


# ---------------------------------------------------------------- 素材形态

def _words(text, step=0.35, pause=0.0):
    out, t = [], 1.0
    for tok in text.split():
        out.append({"w": tok, "start": round(t, 3), "end": round(t + 0.3, 3)})
        t += step + pause
    return out


def test_profile_detects_shadowing():
    from ipa_study import profile
    # 每句念两遍，句间留 4 秒 —— 跟读教材的形状
    text = ""
    for s in ["I check my phone .", "I make some coffee .", "I leave the house ."] * 6:
        text += s + " " + s + "   "
    words, t = [], 1.0
    for group in text.split("   "):
        if not group.strip():
            continue
        for tok in group.split():
            words.append({"w": tok, "start": round(t, 3), "end": round(t + 0.3, 3)})
            t += 0.35
        t += 4.0
    a = profile.analyze(words)
    v = profile.verdict(a)
    assert v["shape"] == "shadowing", v
    assert v["settings"].get("asr.dedupe.enabled") is True
    assert v["settings"].get("asr.itemwise.enabled") is True


def test_profile_detects_narrative():
    from ipa_study import profile
    # 每句都不一样：用 20 个词轮转的话，每 20 句就整段重复一次，
    # find_duplicate 会正确地把它判成重复语料（那不是测试想要的）
    words, t = [], 1.0
    for k in range(220):
        for j in range(9):
            tok = f"w{k}x{j}"
            words.append({"w": tok, "start": round(t, 3), "end": round(t + 0.25, 3)})
            t += 0.25
        t += 0.45
    v = profile.verdict(profile.analyze(words))
    assert v["shape"] == "narrative", v
    assert v["settings"].get("asr.dedupe.enabled") is None


def test_dedupe_keeps_first_copy():
    from ipa_study import dedupe
    words = _words("I go to the bathroom I go to the bathroom")
    kept, removed, rep = dedupe.apply_items(words, gap=3.0)
    assert len(removed) == 5
    assert " ".join(w["w"] for w in kept) == "I go to the bathroom"


def test_form_for_prefers_word_count():
    assert CZ.form_for(4000, n_words=1200)["kind"] == "single"
    assert CZ.form_for(4000, n_words=3000)["kind"] == "sections"
    assert CZ.form_for(4000, n_words=11428) == {"kind": "book", "k": 12}


# ---------------------------------------------------------------- 金标准

def test_golden_metrics_and_render():
    """拿仓库里的示例做回归。

    仓库只带第 1 章的标注（整部片的逐字转写不适合公开），所以逐章比
    每章的计数，而不是全书总数；页数断言也按实际有多少章来放宽。
    本地如果跑过 import-legacy 拿到了全部 12 章，会走更严的那条断言。
    """
    from ipa_study import stats, render, qa

    job = CFG.Job.load(ROOT / "examples" / "steve-jobs" / "job.json")
    expected = json.loads((ROOT / "examples" / "steve-jobs" /
                           "expected_metrics.json").read_text(encoding="utf-8"))

    units = {}
    for ch in job.chapters:
        p = job.data_dir / f"ch{ch.id:02d}_ann.json"
        if p.exists():
            units[ch.id] = json.loads(p.read_text(encoding="utf-8"))
    assert units, "示例标注缺失"

    for ch_id, u in units.items():
        got = stats.count(u)
        exp = expected["per_chapter"][str(ch_id)]
        for key in ("words", "sentences", "accent"):
            assert got[key] == exp[key], (ch_id, key, got[key], exp[key])

    out = Path(tempfile.gettempdir()) / "ipa_golden.pdf"
    s = stats.doc_stats(job, units)
    render.build_book(job, units, s, out)
    rep = qa.pdf_report(out)
    if len(units) == len(job.chapters):
        assert rep["pages"] == 100, rep
    else:
        assert rep["pages"] >= 10, rep
    assert rep["missing_glyphs"] == 0, rep


def main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
