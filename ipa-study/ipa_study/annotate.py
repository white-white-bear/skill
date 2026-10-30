# -*- coding: utf-8 -*-
"""逐词标注：音标、音节配时、音高、H/M/L、语调走向、弱读、连读、失爆、吞音、浊化。

测量与规则的边界：
- 实测：每词时长、峰值响度、基频、音节内基频
- 规则：弱读替换、连读类型、失爆/吞音/浊化（在音素序列上按下标判定）
- 插值：浊音段数与音节数对不上时的音节配时
"""
from __future__ import annotations

import numpy as np

from . import lexicon as LX
from . import phonology as P
from .acoustics import voice_runs

WEAK_ARP = {
    "a": ("EY1", "AH0"), "an": ("AE1 N", "AH0 N"),
    "and": ("AE1 N D", "AH0 N"), "of": ("AH1 V", "AH0 V"),
    "to": ("T UW1", "T AH0"), "at": ("AE1 T", "AH0 T"),
    "for": ("F AO1 R", "F ER0"), "from": ("F R AH1 M", "F R AH0 M"),
    "as": ("AE1 Z", "AH0 Z"), "but": ("B AH1 T", "B AH0 T"),
    "than": ("DH AE1 N", "DH AH0 N"), "that": ("DH AE1 T", "DH AH0 T"),
    "was": ("W AH1 Z", "W AH0 Z"), "were": ("W ER1", "W ER0"),
    "is": ("IH1 Z", "IH0 Z"), "are": ("AA1 R", "ER0"),
    "am": ("AE1 M", "AH0 M"), "be": ("B IY1", "B IY0"),
    "has": ("HH AE1 Z", "HH AH0 Z"), "have": ("HH AE1 V", "HH AH0 V"),
    "had": ("HH AE1 D", "HH AH0 D"), "do": ("D UW1", "D AH0"),
    "does": ("D AH1 Z", "D AH0 Z"), "did": ("D IH1 D", "D AH0 D"),
    "can": ("K AE1 N", "K AH0 N"), "could": ("K UH1 D", "K AH0 D"),
    "would": ("W UH1 D", "W AH0 D"), "should": ("SH UH1 D", "SH AH0 D"),
    "will": ("W IH1 L", "W AH0 L"), "some": ("S AH1 M", "S AH0 M"),
    "his": ("HH IH1 Z", "HH IH0 Z"), "him": ("HH IH1 M", "HH IH0 M"),
    "her": ("HH ER1", "HH ER0"), "them": ("DH EH1 M", "DH AH0 M"),
    "us": ("AH1 S", "AH0 S"), "me": ("M IY1", "M IY0"),
    "your": ("Y AO1 R", "Y ER0"), "our": ("AW1 ER0", "AA1 R"),
    "you": ("Y UW1", "Y AH0"), "he": ("HH IY1", "HH IY0"),
    "she": ("SH IY1", "SH IY0"), "we": ("W IY1", "W IY0"),
    "they": ("DH EY1", "DH EY0"), "there": ("DH EH1 R", "DH ER0"),
    "into": ("IH1 N T UW0", "IH0 N T AH0"),
}


def phones_for(word, pos=0):
    key = LX_clean(word)
    if key in WEAK_ARP:
        strong, weak = WEAK_ARP[key]
        return strong.split(), weak.split()
    ph = LX.lookup(word, pos)
    return (list(ph), list(ph)) if ph else (None, None)


def LX_clean(word: str) -> str:
    from .tokenize import norm
    return norm(word)


def syllable_spans(track, a, b, sylls):
    """音节配时：浊音段数量对得上就照用，否则按音素数成比例摊。"""
    n = len(sylls)
    runs = voice_runs(track, a, b)
    if len(runs) == n:
        return runs, "voiced"
    if len(runs) > n:
        return sorted(sorted(runs, key=lambda r: r[1] - r[0], reverse=True)[:n]), "voiced"
    counts = [max(1, len(s["phones"])) for s in sylls]
    total = sum(counts)
    spans, cur = [], a
    for c in counts:
        w = (b - a) * c / total
        spans.append((cur, cur + w))
        cur += w
    return spans, "distributed"


def measure(track, a, b):
    m = (track.f0_t >= a) & (track.f0_t <= b)
    f0 = track.f0[m]
    v = f0[f0 > 60]
    mi = (track.in_t >= a) & (track.in_t <= b)
    iv = track.in_v[mi]
    iv = iv[np.isfinite(iv)]
    st = 12 * np.log2(v / track.base) if len(v) else np.array([])
    slope = 0.0
    if len(v) >= 4:
        slope = float(np.polyfit(track.f0_t[m][f0 > 60], st, 1)[0])
    return dict(dur=float(b - a),
                f0=float(np.median(v)) if len(v) else 0.0,
                st=float(np.median(st)) if len(st) else None,
                st_max=float(np.max(st)) if len(st) else None,
                int_max=float(np.max(iv)) if len(iv) else 0.0,
                int_med=float(np.median(iv)) if len(iv) else 0.0,
                slope=slope)


def zs(v):
    a = np.array(v, dtype=float)
    sd = a.std()
    return (a - a.mean()) / sd if sd > 1e-6 else np.zeros_like(a)


def vowel_change(strong, weak):
    def nucleus(phones):
        for p in phones:
            if LX.strip_stress(p) in LX.VOWELS:
                return p
        return None
    a, b = nucleus(strong), nucleus(weak)
    if a is None or b is None:
        return ""
    ia, ib = LX.phone_ipa(a), LX.phone_ipa(b)
    return "" if ia == ib else f"{ia}→{ib}"


def build_syllables(track, w):
    spoken = P.spoken_variants(w["surface"])
    span = w["end"] - w["start"]
    counts = []
    for sp in spoken:
        strong, _ = phones_for(sp)
        counts.append(max(1, len(strong or ["AH0"])))
    total = sum(counts)
    cur = w["start"]
    sylls, phones, timing = [], [], []
    for sp, c in zip(spoken, counts):
        a = cur
        b = cur + span * c / total
        cur = b
        strong, weak = phones_for(sp)
        if strong is None:
            strong, weak = ["AH1", "N"], ["AH0", "N"]
        sy = LX.syllabify(strong)
        spans, how = syllable_spans(track, a, b, sy)
        timing.append(how)
        for s, (sa, sb) in zip(sy, spans):
            s["a"], s["b"] = sa, sb
            s.update(measure(track, sa, sb))
            s["word"] = sp
            sylls.append(s)
        phones += strong
    return spoken, phones, sylls, timing


def annotate(units, track, cfg=None):
    cfg = cfg or {}
    acc_th = float(cfg.get("accent_threshold", 0.62))
    level_st = float(cfg.get("level_semitones", 2.2))
    contour_th = float(cfg.get("contour_semitones_per_sec", 3.5))
    link_gap = float(cfg.get("link_gap_sec", 0.06))

    for para in units:
        for sent in para["sents"]:
            ws = sent["words"]
            for w in ws:
                w["spoken"], w["phones"], w["sylls"], w["timing"] = \
                    build_syllables(track, w)
                w["is_clitic"] = LX_clean(w["surface"]) in P.CLITIC
                w["ipa_cite"] = LX.to_ipa(w["phones"])[0]

            mains = []
            for w in ws:
                sy = w["sylls"]
                idx = next((i for i, s in enumerate(sy) if s["stress"] == 1), None)
                if idx is None:
                    idx = int(np.argmax([s["dur"] for s in sy])) if sy else 0
                mains.append(sy[idx] if sy else
                             dict(dur=0, st=0, st_max=0, int_max=0, slope=0))
            # 时长用整词而不是重读音节：否则 outsider 这种多音节词会因为
            # 重读音节短而被系统性地压低
            zd = zs([w["end"] - w["start"] for w in ws])
            zi = zs([m["int_max"] for m in mains])
            zp = zs([(m["st_max"] or 0) for m in mains])
            sent_st = [m["st"] for m in mains if m["st"] is not None]
            sent_med = float(np.median(sent_st)) if sent_st else 0.0

            n = max(1, len(ws) - 1)
            for k, w in enumerate(ws):
                m = mains[k]
                # 时序位置微调：英语的调核倾向落在句末，越靠后给一点加成，
                # 但不足以压过明显的时长/响度证据
                score = 0.50 * zd[k] + 0.30 * zi[k] + 0.20 * zp[k] + 0.18 * (k / n)
                w["accent"] = bool(score > acc_th and not w["is_clitic"])
                w["prom"] = float(score)
                st = m["st"] if m["st"] is not None else sent_med
                rel = st - sent_med
                w["rel_st"] = float(rel)
                w["level"] = "H" if rel > level_st else ("L" if rel < -level_st else "M")
                w["contour"] = ("↗" if m["slope"] > contour_th
                                else ("↘" if m["slope"] < -contour_th else "→"))
                w["main_dur"] = float(m["dur"])
                w["main_f0"] = float(m["f0"])
                w["main_st"] = float(st)
            sent["med_st"] = sent_med

            # 没有对齐到任何时间戳的词（VAD 吞掉的片段）不做重读判定：
            # 它的时间是从邻居插值来的，测出来的音高不能当作证据
            for w in ws:
                if w.get("asr") is None:
                    w["accent"] = False

            # 每个句子至少有一个核心重音。短句的 z 分数会被压平，这时按英语的
            # 默认规律取句末最后一个实词（句末调核），除非别处时长明显更长
            if not any(w["accent"] for w in ws):
                cand = [w for w in ws if not w["is_clitic"]] or ws
                last = cand[-1]
                longer = max(cand, key=lambda w: w["main_dur"])
                best = longer if longer["main_dur"] > last["main_dur"] * 1.8 else last
                best["accent"] = True

            # 重读虚词不弱化；非重读虚词换成弱读形，再算词尾变化
            for w in ws:
                w["weak"] = None
                key = LX_clean(w["surface"])
                if not w["accent"] and key in WEAK_ARP and len(w["spoken"]) == 1:
                    strong, weak = phones_for(key)
                    if strong and weak:
                        # 比较时不带重音符号，否则 /ˈhɪz/ 与 /hɪz/ 会被误当成"元音变化"
                        cite = LX.to_ipa(strong, stress_marks=False)[0]
                        weak_ipa = LX.to_ipa(weak, stress_marks=False)[0]
                        if cite != weak_ipa:
                            w["weak"] = dict(cite=cite, weak=weak_ipa,
                                             vowel=vowel_change(strong, weak))
                            w["phones"] = list(weak)

            # 词尾变化 + 连读（在最终音素序列上判定）
            for k, w in enumerate(ws):
                nxt = ws[k + 1] if k + 1 < len(ws) else None
                nx = nxt["phones"][0] if nxt else None
                gap = (nxt["start"] - w["end"]) if nxt else 1.0
                last = w["phones"][-1] if w["phones"] else None
                sentence_final = nxt is None
                nx_vowel = bool(nx) and LX.strip_stress(nx) in LX.VOWELS
                unrel, elid, flap = P.final_changes(
                    w["phones"], nxt["phones"] if nxt else None,
                    sentence_final, nx_vowel)
                w["unreleased"] = sorted(unrel)
                w["elided"] = sorted(elid)
                w["flapped"] = sorted(flap)
                w["link"] = P.link_type(last, nx) if (nxt and gap < link_gap) else None
                w["gap_next"] = float(gap)

            for w in ws:
                breaks, prev = set(), None
                for i, s in enumerate(w["sylls"]):
                    if prev is not None and s["word"] != prev:
                        breaks.add(i)
                    prev = s["word"]
                # 弱读替换后音节结构变了，必须重新切分；否则沿用已配时的音节
                use_sylls = None if w.get("weak") else w["sylls"]
                w["ipa"] = P.render_word(w["phones"], w["unreleased"], w["elided"],
                                         w["flapped"], show_stress=not w["is_clitic"],
                                         breaks=breaks, sylls=use_sylls).strip()
    return units


def timing_report(units) -> dict:
    """音节配时里"按音素摊分"的比例。整章都在摊，说明声学对齐出了问题。"""
    from collections import Counter
    c = Counter()
    for p in units:
        for s in p["sents"]:
            for w in s["words"]:
                for how in w.get("timing", []):
                    c[how] += 1
    tot = sum(c.values()) or 1
    return {"voiced": c["voiced"], "distributed": c["distributed"],
            "distributed_ratio": round(c["distributed"] / tot, 4)}
