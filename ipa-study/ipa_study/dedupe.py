# -*- coding: utf-8 -*-
"""去掉跟读教材里"每句念两遍"的重复。

两套算法：

- `apply_items`（默认）：先按长停顿把词流切成"条目"（一条 = 一句话 + 它的
  重念），再在条目内部找**最长的重复段**，保留前半。
  比逐词比对稳得多：转写常把上一句的尾词漏进这一句，两半字数就对不齐，
  逐词比对会判失败，找最长重复段则不受影响。

- `apply`（旧的逐词版）：只在材料节奏规整时用。保留是因为它更保守。

默认关闭。演讲里的排比（"I have a dream"反复出现）间隔更长、中间还有别的
内容，不会被误删；但删错了最难发现，所以由人显式打开。
"""
from __future__ import annotations

from . import tokenize as TK

ITEM_GAP_SEC = 3.0
MIN_RUN = 3
MIN_COVER = 0.5


def _norm(w):
    return TK.norm(w["w"])


# 转写会把下一句的开头词卡在长停顿之前，并把它拉长到填满空隙。
# 这些词出现在条目末尾几乎一定是这个毛病，不是真的句尾。
_LEADING_WORDS = {"i", "im", "ive", "ill", "id", "we", "were", "you", "youre",
                  "he", "shes", "she", "they", "it", "its", "thats", "can",
                  "could", "do", "does", "did", "what", "how", "where", "when",
                  "the", "a", "an", "my", "his", "her", "our", "your", "there",
                  "this", "these", "those", "if", "let", "lets", "is", "are",
                  "was", "have", "has", "would", "should", "will", "didnt",
                  "dont", "sorry", "thanks", "thank"}


def repair_boundaries(items: list, stretch_ms: float = 700) -> int:
    """把卡在条目末尾的下一句首词挪到下一句开头。

    判据要两个同时成立：词本身是常见的句首词，**且**它的时长被拉长了。
    只看词性会把 "...and I" 这种正常结尾也挪走。
    """
    moved = 0
    for k in range(len(items) - 1):
        cur, nxt = items[k], items[k + 1]
        if not cur or not nxt:
            continue
        last = cur[-1]
        if _norm(last) not in _LEADING_WORDS:
            continue
        if (last["end"] - last["start"]) * 1000 < stretch_ms:
            continue
        cur.pop()
        # 时间戳也得跟着挪，否则词在文本上归了下一句、在时间轴上还挂在
        # 上一句末尾，一按停顿分段又会碎掉。给个贴住下一词的短区间，
        # 声学上量不出音高，正好让它不参与重读判定。
        anchor = nxt[0]["start"]
        floor = cur[-1]["end"] if cur else anchor - 0.15
        last["start"] = round(max(floor, anchor - 0.12), 3)
        last["end"] = round(max(last["start"] + 0.04, anchor - 0.001), 3)
        last["repaired"] = True
        nxt.insert(0, last)
        moved += 1
    return moved


def split_items(words: list, gap: float = ITEM_GAP_SEC) -> list:
    """按长停顿切成条目。这些停顿是练习留白，比句子边界更硬。"""
    if not words:
        return []
    items, cur = [], [words[0]]
    for a, b in zip(words, words[1:]):
        if b["start"] - a["end"] > gap:
            items.append(cur)
            cur = []
        cur.append(b)
    items.append(cur)
    return items


def _longest_run(tok: list, min_run: int = MIN_RUN):
    """条目内最长的重复段，返回 (起点, 第二遍起点, 长度)。"""
    n = len(tok)
    best = (0, 0, 0)
    for i in range(n):
        for j in range(i + min_run, n):
            L = 0
            while j + L < n and tok[i + L] == tok[j + L] and tok[i + L]:
                L += 1
            if L > best[2]:
                best = (i, j, L)
    return best


def find_duplicate(item: list, min_run: int = MIN_RUN,
                   min_cover: float = MIN_COVER):
    """返回要丢弃的起始下标（第二遍的起点），不是重复就返回 None。"""
    tok = [_norm(w) for w in item]
    i, j, L = _longest_run(tok, min_run)
    if L < min_run:
        return None
    # 第一遍必须从条目开头附近开始，第二遍要覆盖掉大半个条目，
    # 否则可能是句中的普通词组重复，不是"整句念两遍"
    if i > 2:
        return None
    if (j - i) + L < len(tok) * min_cover:
        return None
    return j


def apply_items(words: list, gap: float = ITEM_GAP_SEC,
                min_run: int = MIN_RUN) -> tuple:
    """返回 (保留的词, 被删的词, 报告)。保留第一遍。"""
    items = split_items(words, gap)
    repair_boundaries(items)
    kept, removed, detail = [], [], []
    for it in items:
        j = find_duplicate(it, min_run)
        if j is None:
            kept.extend(it)
            continue
        kept.extend(it[:j])
        removed.extend(it[j:])
        detail.append({
            "start": round(it[0]["start"], 2),
            "first": " ".join(w["w"].strip() for w in it[:j]),
            "dropped": " ".join(w["w"].strip() for w in it[j:]),
        })
    return kept, removed, {"items": len(items), "duplicates": len(detail),
                           "detail": detail}


# ---------------------------------------------------------------- 旧版

def find_repeats(words: list, max_gap: float = 2.0,
                 min_n: int = 3, max_n: int = 14) -> list:
    norm = [_norm(w) for w in words]
    out, i = [], 0
    while i < len(norm) - min_n:
        hit = None
        for n in range(max_n, min_n - 1, -1):
            if i + 2 * n > len(norm):
                continue
            if norm[i:i + n] != norm[i + n:i + 2 * n]:
                continue
            gap = words[i + n]["start"] - words[i + n - 1]["end"]
            if gap > max_gap:
                continue
            hit = (i, n, round(gap, 2))
            break
        if hit:
            out.append(hit)
            i += 2 * hit[1]
        else:
            i += 1
    return out


def apply(words: list, max_gap: float = 2.0) -> tuple:
    reps = find_repeats(words, max_gap)
    drop = set()
    for start, n, _gap in reps:
        drop.update(range(start + n, start + 2 * n))
    kept = [w for k, w in enumerate(words) if k not in drop]
    removed = [w for k, w in enumerate(words) if k in drop]
    detail = [{"start": round(words[s]["start"], 2), "n": n, "gap": g,
               "text": " ".join(w["w"].strip() for w in words[s:s + n])}
              for s, n, g in reps]
    return kept, removed, detail
