# -*- coding: utf-8 -*-
"""文本整理：从词级时间戳生成断好句、分好段的草稿。

断句的硬证据是**停顿**，不是猜出来的标点。Whisper 自己给的 segment 标点
是免费证据，有就采信；没有就按停顿断开，句首大写、句尾补句号，交给 agent
在纯文本上修订。这样 agent 改的是文字，不会顺手把词也改了 —— 改词会让
音标和音频错位，是这个产品最隐蔽的失效方式。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import lexicon as LX
from . import tokenize as TK


# ---------------------------------------------------------------- 粘连词

FUNCTION_WORDS = {"a", "an", "the", "in", "on", "of", "to", "and", "or",
                  "at", "for", "from", "with", "as", "but", "is", "was",
                  "it", "he", "she", "we", "they", "you", "i"}


def _known(w: str) -> bool:
    return bool(LX.lookup(w)) or w in FUNCTION_WORDS


def split_glued(word: str, context: list | None = None) -> list:
    """把 whilein 这类粘词拆开。拆不动就原样返回，交给 review。"""
    w = TK.norm(word)
    if len(w) < 6 or not w.isalpha():
        return [word]
    # 整词本身就在词典里就绝不能拆。少了这一句，carefully→care fully、
    # bathroom→bath room、breakfast→break fast 都会被拆坏——两半都在
    # 词典里只是必要条件，不是充分条件。
    if LX.lookup(w):
        return [word]
    cands = []
    for i in range(2, len(w) - 1):
        a, b = w[:i], w[i:]
        if not (_known(a) and _known(b)):
            continue
        score = min(len(a), len(b)) * 0.4
        if a in FUNCTION_WORDS or b in FUNCTION_WORDS:
            score += 1.2
        if context:
            ctx = {TK.norm(x) for x in context}
            score += 0.8 * ((a in ctx) + (b in ctx))
        cands.append((score, a, b))
    if not cands:
        return [word]
    cands.sort(reverse=True)
    best = cands[0]
    # 分数不够领先就不拆：拆错比不拆难查得多
    if len(cands) > 1 and best[0] - cands[1][0] < 0.5:
        return [word]
    if best[0] < 1.0:
        return [word]
    return [best[1], best[2]]


def normalise_words(words: list) -> tuple:
    """拆粘词并统一词形，返回 (words, 报告)。最慢的一步是词典查询，只查一次。"""
    out, glued = [], []
    for k, w in enumerate(words):
        parts = TK.tokenize(w["w"]) or [w["w"]]
        if len(parts) == 1:
            parts = split_glued(w["w"], [x["w"] for x in words[max(0, k - 3):k + 4]])
        if len(parts) > 1:
            glued.append({"at": w["start"], "from": w["w"], "to": parts})
            span = w["end"] - w["start"]
            weights = [max(1, len(p)) for p in parts]
            tot = sum(weights)
            cur = w["start"]
            for p, wt in zip(parts, weights):
                d = span * wt / tot
                out.append({"w": p, "start": round(cur, 3),
                            "end": round(cur + d, 3), **{k2: v for k2, v in w.items()
                                                         if k2 not in ("w", "start", "end")}})
                cur += d
        else:
            out.append(dict(w))
    return out, glued


# ---------------------------------------------------------------- 断句

END_PUNCT = (".", "!", "?", "…", "。", "！", "？")
_TERMINAL = re.compile(r"[.!?…]['\"”’)]*$")


def _seg_ends(segments: list) -> list:
    """Whisper segment 里已经带句末标点的结束时间。"""
    return [s["end"] for s in segments
            if s.get("text") and _TERMINAL.search(s["text"].strip())]


def build_sentences(words: list, cfg: dict, seg_ends: list | None = None) -> list:
    """返回 [[词...]...]；词是 dict，带 start/end/w。

    句界取自停顿 >= sentence_gap_sec，且当前句至少 min_sentence_words 个词；
    Whisper 的句末标点位置同样算一次句界（那是免费的、来自声学模型的判断）。
    """
    gap_s = float(cfg.get("sentence_gap_sec", 0.60))
    para_s = float(cfg.get("paragraph_gap_sec", 1.50))
    min_w = int(cfg.get("min_sentence_words", 4))
    max_w = int(cfg.get("max_sentence_words", 45))
    seg_ends = seg_ends or []

    sentences, cur = [], []
    prev_end = None
    for w in words:
        if cur:
            gap = w["start"] - prev_end
            near_end = any(prev_end - 0.15 <= e <= w["start"] + 0.05 for e in seg_ends)
            long_enough = len(cur) >= min_w
            too_long = len(cur) >= max_w
            if (gap >= gap_s and long_enough) or (near_end and long_enough) or too_long:
                sentences.append(cur)
                cur = []
        cur.append(w)
        prev_end = w["end"]
    if cur:
        sentences.append(cur)
    return sentences


def group_paragraphs(sentences: list, cfg: dict) -> list:
    """段界：句间停顿 >= paragraph_gap_sec，或每 5 句一段。"""
    para_s = float(cfg.get("paragraph_gap_sec", 1.50))
    paras, cur = [], []
    for i, s in enumerate(sentences):
        if cur:
            gap = s[0]["start"] - cur[-1][-1]["end"]
            if gap >= para_s or len(cur) >= 5:
                paras.append(cur)
                cur = []
        cur.append(s)
    if cur:
        paras.append(cur)
    return paras


def render_text(paragraphs: list) -> str:
    """把词序列排成可编辑的纯文本：一句一行，句首大写、句尾句号。"""
    out = []
    for para in paragraphs:
        lines = []
        for sent in para:
            words = [w["w"] for w in sent]
            if not words:
                continue
            body = " ".join(words)
            lines.append(body)
        out.append("\n".join(lines))
    return "\n\n".join(out)


def capitalise(text: str) -> str:
    """只动首字母和句末标点；一个词都不增删，保证 token 序列不变。"""
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            out.append("")
            continue
        line = line[0].upper() + line[1:]
        # 句号后如果还有半句（转写常把两句连在一个停顿里），也把首字母大写，
        # 否则读起来分不清哪儿是哪儿
        line = re.sub(r"([.!?])\s+([a-z])", lambda m: f"{m.group(1)} {m.group(2).upper()}", line)
        if not _TERMINAL.search(line) and not line.endswith((",", ";", ":")):
            line += "."
        out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------- 复查

def review(paragraphs: list, glued: list, cfg: dict) -> dict:
    max_w = int(cfg.get("max_sentence_words", 45))
    long_sents = []
    for pi, para in enumerate(paragraphs):
        for si, sent in enumerate(para):
            if len(sent) > max_w:
                long_sents.append({"para": pi, "sent": si, "words": len(sent),
                                   "text": " ".join(w["w"] for w in sent)[:160]})
    unsplit = [g for g in glued if len(g["to"]) == 1]
    return {"glued": glued, "unsplit": unsplit,
            "too_long": long_sents,
            "needs_review": bool(unsplit or long_sents)}


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_text(path: Path) -> list:
    """读回可编辑文本 → [[[词]...]...]，后续对齐只吃这个结构。"""
    if not path.exists():
        return []
    paras = []
    for block in path.read_text(encoding="utf-8").split("\n\n"):
        block = block.strip("\n")
        if not block.strip():
            continue
        sents = []
        for line in block.split("\n"):
            line = line.strip()
            if not line:
                continue
            tp = TK.tokenize_punct(line)
            if tp:
                sents.append(tp)
        if sents:
            paras.append(sents)
    return paras
