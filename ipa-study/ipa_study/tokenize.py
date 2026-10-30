# -*- coding: utf-8 -*-
"""记号化与序列对齐。对齐代价函数是全流程共用的。"""
from __future__ import annotations

import re

import numpy as np

WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?")
OPENING = "“\"'«("


def tokenize(text: str) -> list:
    """保留原词形（含撇号），连字符拆成两个词。"""
    return [m.group(0) for m in WORD_RE.finditer(text)]


def norm(tok: str) -> str:
    return re.sub(r"[^a-z0-9]", "", tok.lower())


def tokenize_punct(sent: str) -> list:
    """返回 [(前引号, 词, 尾随标点)]，用来在排版时还原句读。"""
    ms = list(WORD_RE.finditer(sent))
    if not ms:
        return []
    head = sent[:ms[0].start()].strip()
    carry = head if head and all(ch in OPENING for ch in head) else ""
    out = []
    for i, m in enumerate(ms):
        next_start = ms[i + 1].start() if i + 1 < len(ms) else len(sent)
        raw = sent[m.end():next_start]
        body = raw.strip()
        if raw[:1].isspace():
            carry_next = body if all(ch in OPENING for ch in body) else ""
            tail = "" if carry_next else body
        else:
            parts = body.split(None, 1) if body else []
            tail = parts[0] if parts else ""
            after = parts[1].strip() if len(parts) > 1 else ""
            if after and all(ch in OPENING for ch in after):
                carry_next = after
            else:
                tail = (tail + after).strip()
                carry_next = ""
        out.append([carry, m.group(0), tail])
        carry = carry_next
    if carry and out:
        out[-1][2] += carry
    return [tuple(x) for x in out]


def _cost(x: str, y: str, sub: float) -> float:
    if x == y:
        return 0.0
    if x.startswith(y) or y.startswith(x):
        return 0.35
    return sub


def _nw(a, b, gap: float, sub: float, band):
    n, m = len(a), len(b)
    INF = float("inf")
    dp = np.full((n + 1, m + 1), INF, dtype=np.float64)
    dp[0, 0] = 0.0
    lim_i = n if band is None else min(band, n)
    lim_j = m if band is None else min(band, m)
    for i in range(1, lim_i + 1):
        dp[i, 0] = dp[i - 1, 0] + gap
    for j in range(1, lim_j + 1):
        dp[0, j] = dp[0, j - 1] + gap

    for i in range(1, n + 1):
        jlo = 1 if band is None else max(1, i - band)
        jhi = m if band is None else min(m, i + band)
        if jlo > jhi:
            continue
        row, up_row = dp[i], dp[i - 1]
        for j in range(jlo, jhi + 1):
            c = _cost(a[i - 1], b[j - 1], sub)
            row[j] = min(up_row[j - 1] + c, up_row[j] + gap, row[j - 1] + gap)

    if not np.isfinite(dp[n, m]):
        return None

    i, j, pairs = n, m, []
    while i > 0 and j > 0:
        c = _cost(a[i - 1], b[j - 1], sub)
        if abs(dp[i, j] - (dp[i - 1, j - 1] + c)) < 1e-6:
            pairs.append((i - 1, j - 1)); i -= 1; j -= 1
        elif abs(dp[i, j] - (dp[i - 1, j] + gap)) < 1e-6:
            pairs.append((i - 1, None)); i -= 1
        else:
            j -= 1
    while i > 0:
        pairs.append((i - 1, None)); i -= 1
    return pairs[::-1]


def align_seq(a, b, gap=1.0, sub=1.25, band=None):
    """Needleman-Wunsch。a 是正文词，b 是 ASR 词，返回 [(i, j|None)]。

    band 给定时限带宽（|i-j| <= band），复杂度从 O(nm) 降到 O(n*band)。
    带太窄导致终点不可达时自动放宽，最多放到不限带宽。
    """
    if band is None:
        return _nw(a, b, gap, sub, None)
    for width in (band, band * 2, band * 4):
        got = _nw(a, b, gap, sub, width)
        if got is not None:
            return got
    return _nw(a, b, gap, sub, None)


def align_text(text_tokens, asr_words, band=None):
    """返回 (pairs, asr_flat)。asr_words 形如 [{'w','start','end'}]。"""
    asr_norm, asr_flat = [], []
    for w in asr_words:
        for t in tokenize(w["w"]):
            asr_norm.append(norm(t))
            asr_flat.append(t)
    pairs = align_seq([norm(t) for t in text_tokens], asr_norm, band=band)
    return pairs, asr_flat
