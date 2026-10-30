# -*- coding: utf-8 -*-
"""把正文对齐到词级时间戳。

三种模式自动选：
- identity：正文就是同一段 ASR（只加了标点），按下标直配，O(n)
- banded：两侧高度相似但不等长，带宽 DP
- windowed_nw：真正的不同版本文案，先用"前 40 词最长连续命中段"找锚点再开窗对齐

章节窗口只来自 job.chapters，且强制非重叠 —— 旧实现用 PDF 目录的秒数开窗，
把 ch05 和 ch06 串了 19.76 秒。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import lexicon as LX
from . import tokenize as TK


# ---------------------------------------------------------------- 模式判定

def _close(x: str, y: str) -> bool:
    return x == y or x.startswith(y) or y.startswith(x)


def precheck(text_tokens: list, window_words: list, band: int = 24) -> dict:
    """判定该用哪种对齐方式。

    相似度不能用"逐位比对"：正文和转写只要中间错开一个词，后面全对不上，
    逐位得分会掉到 0.1，把明明只是错位的两份文本判成完全不同。这里用带宽
    DP 的**实际匹配率**，错位多少就付出多少代价。
    """
    a = [TK.norm(t) for t in text_tokens]
    b = [TK.norm(w2) for w in window_words for w2 in TK.tokenize(w["w"])]
    n, m = len(a), len(b)
    if not n or not m:
        return {"mode": "windowed_nw", "match": 0.0, "ratio": 0.0,
                "n_text": n, "n_asr": m}

    positional = sum(1 for x, y in zip(a, b) if _close(x, y))
    ratio = n / m
    if n == m and positional / n >= 0.98:
        return {"mode": "identity", "match": round(positional / n, 4),
                "ratio": round(ratio, 4), "n_text": n, "n_asr": m}

    pairs = TK.align_seq(a, b, band=band)
    matched = sum(1 for _, j in pairs if j is not None)
    match = matched / max(n, m)
    # 一旦有六成词能配上，就说明只是局部增删，带宽 DP 足够；再低才是
    # 真正不同的两版本文案，需要先找锚点再开窗
    mode = "banded" if match >= 0.60 else "windowed_nw"
    return {"mode": mode, "match": round(match, 4), "ratio": round(ratio, 4),
            "n_text": n, "n_asr": m}


def locate(flat_norm: list, asr_norm: list, start: int = 0) -> int | None:
    """用开头 40 个词找锚点，取**最长连续命中段**的起点。

    只看单个命中会被 "the" 这类孤立词骗走；只看最后一个命中又会被吸到文件
    末尾（探针结束后剩下的参考词无论落在哪都要记成空位，末尾几组对位几乎打平）。
    """
    probe = flat_norm[:40]
    ref = asr_norm[start:]
    if not probe or not ref:
        return None
    pairs = TK.align_seq(probe, ref)
    best_len, best_j, run, run_start = 0, None, 0, None
    pi = pj = None
    for i, j in pairs:
        if j is None:
            run, pi = 0, None
            continue
        if pi is not None and i == pi + 1 and j == pj + 1:
            run += 1
        else:
            run, run_start = 1, j
        if run > best_len:
            best_len, best_j = run, run_start
        pi, pj = i, j
    if best_j is None or best_len < 4:
        return None
    return start + best_j


# ---------------------------------------------------------------- 对齐

def align_words(text_flat: list, window_words: list, mode: str,
                band: int = 24) -> tuple:
    """返回 (pairs, asr_flat)。asr_flat 与 window_words 展开后的词一一对应。"""
    asr_flat, asr_norm = [], []
    for w in window_words:
        for t in TK.tokenize(w["w"]):
            asr_flat.append(t)
            asr_norm.append(TK.norm(t))
    a = [TK.norm(t) for t in text_flat]

    if mode == "identity" and len(a) == len(asr_norm):
        pairs = [(i, i) if (a[i] == asr_norm[i] or a[i].startswith(asr_norm[i])
                            or asr_norm[i].startswith(a[i]))
                 else (i, None) for i in range(len(a))]
        # identity 下如果重合度骤降，说明判定错了，退回带宽对齐
        if sum(1 for _, j in pairs if j is not None) < len(a) * 0.9:
            mode = "banded"
        else:
            return pairs, asr_flat
    return TK.align_seq(a, asr_norm, band=band if mode == "banded" else None), asr_flat


def _phone_weight(word: str) -> int:
    ph = LX.lookup(word)
    return max(1, len(ph)) if ph else max(1, len(word))


def interpolate(words: list, fallback_t0: float, weight: str = "phones") -> list:
    """未匹配的连续词按音素数在空档里均摊。

    不是每词塞 0.08 秒 —— 那样测出来的时长和音高全无意义。
    """
    k = 0
    while k < len(words):
        if words[k]["start"] is not None:
            k += 1
            continue
        j = k
        while j < len(words) and words[j]["start"] is None:
            j += 1
        s = words[k - 1]["end"] if k > 0 else fallback_t0
        e = words[j]["start"] if j < len(words) else s + 0.25 * (j - k)
        e = max(e, s + 0.06 * (j - k))
        ws = [_phone_weight(w["surface"]) if weight == "phones"
              else max(1, len(w["surface"])) for w in words[k:j]]
        tot = sum(ws) or 1
        cur = s
        for w, wt in zip(words[k:j], ws):
            span = (e - s) * wt / tot
            w["start"], w["end"] = cur, cur + span
            cur += span
        k = j
    return words


def build_chapter(job, ch, text_paras: list, all_words: list) -> dict:
    """text_paras: [[(lead, word, tail)...]] 的段落列表。返回 units + 诊断。"""
    text_flat, meta = [], []
    for para in text_paras:
        for sent in para:
            for lead, word, tail in sent:
                text_flat.append(word)
                meta.append((lead, tail))

    window = [w for w in all_words if ch.start - 0.5 <= w["start"] <= ch.end + 0.5]
    if not window:                       # 章边界落在词间隙外，放宽一点
        window = [w for w in all_words if ch.start - 5 <= w["start"] <= ch.end + 5]
    band = int(job.align.get("band_width", 24))
    diag = precheck(text_flat, window, band=band)

    if diag["mode"] == "windowed_nw":
        asr_norm_all = [TK.norm(t) for w in window for t in TK.tokenize(w["w"])]
        a = locate([TK.norm(t) for t in text_flat], asr_norm_all)
        idx = a if a is not None else 0
        window = window[idx:] if a is not None else window

    pairs, asr_flat = align_words(text_flat, window, diag["mode"], band=band)

    times = [(w["start"], w["end"]) for w in window
             for _ in TK.tokenize(w["w"])]
    words = []
    for i, j in pairs:
        if j is None or j >= len(times):
            words.append(dict(surface=text_flat[i], start=None, end=None, asr=None))
        else:
            words.append(dict(surface=text_flat[i], start=times[j][0],
                              end=times[j][1], asr=asr_flat[j]))

    t0 = window[0]["start"] if window else ch.start
    words = interpolate(words, t0, job.align.get("interpolate_weight", "phones"))

    out, wi = [], 0
    for pi, para in enumerate(text_paras):
        p = dict(para=pi, sents=[])
        for si, sent in enumerate(para):
            chunk = words[wi:wi + len(sent)]
            for w, (lead, _, tail) in zip(chunk, sent):
                w["lead"], w["punct"] = lead, tail
            p["sents"].append(dict(idx=si,
                                   text=" ".join(x[1] for x in sent),
                                   words=chunk))
            wi += len(sent)
        out.append(p)

    miss = sum(1 for w in words if w["asr"] is None)
    diag.update(chapter=ch.id, words=len(words), unmatched=miss,
                unmatched_ratio=round(miss / max(1, len(words)), 4),
                first_word=words[0]["surface"] if words else "",
                last_word=words[-1]["surface"] if words else "",
                t0=round(words[0]["start"], 2) if words else ch.start,
                t1=round(words[-1]["end"], 2) if words else ch.end)
    return {"units": out, "diag": diag}
