# -*- coding: utf-8 -*-
"""自动分章：静音候选 + 特征打分 + DP，最后交给 agent 做编辑判断。

分章本质是编辑动作，不是算法。这里只负责把"值得在哪儿切"的证据摆出来：
停顿多长、前后是不是换了话题、语调有没有重置、离理想间距多远。真正切在哪
由 agent 定 —— 算法切出来的章节标题会是对的，但读起来是断的。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from . import stats as S
from . import tokenize as TK

STOP = set("""a an the and or but if of to in on at for from with as is was were
are be been being it its this that these those he she they we you i his her their
our your my me him them us not no so just very really well now then there here
what which who whom whose when where why how all any some more most other into
about over under out up down do does did done have has had will would can could
should may might must than too also only own same such nor""".split())


# ---------------------------------------------------------------- 形态

def form_for(duration: float, n_words: int | None = None) -> dict:
    """选形态。有词数时按**内容量**算，没词数才按时长兜底。

    时长会骗人：跟读教材 68 分钟里说出来的话可能只有 3000 词，按 68 分钟
    套"分章全书"会得到一本每章只有 250 词的书。
    """
    if n_words:
        if n_words < 1500:
            return {"kind": "single", "k": 1}
        if n_words < 6000:
            return {"kind": "sections", "k": max(3, min(8, round(n_words / 500)))}
        return {"kind": "book", "k": max(8, min(14, round(n_words / 950)))}
    minutes = duration / 60.0
    if minutes < 12:
        return {"kind": "single", "k": 1}
    if minutes < 60:
        return {"kind": "sections", "k": max(3, min(6, round(minutes / 10)))}
    return {"kind": "book", "k": max(8, min(14, round(minutes / 5.5)))}


# ---------------------------------------------------------------- 候选

def _content(words) -> set:
    return {TK.norm(w["w"]) for w in words
            if TK.norm(w["w"]) not in STOP and len(TK.norm(w["w"])) > 2}


def candidates(words: list, cfg: dict, duration: float) -> list:
    """词间隙够长的地方都是候选点。"""
    gap_min = float(cfg.get("candidate_gap_sec", 1.2))
    margin = float(cfg.get("edge_margin_sec", 30.0))
    out = []
    for k in range(1, len(words)):
        a, b = words[k - 1], words[k]
        gap = b["start"] - a["end"]
        if gap < gap_min:
            continue
        mid = (a["end"] + b["start"]) / 2
        if mid < margin or mid > duration - margin:
            continue
        # 前后各 60 词：25 词在 5 分钟一章的尺度上太短，算出来的
        # 词汇衔接几乎是噪声
        out.append({"index": k, "time": mid, "gap": gap,
                    "before": words[max(0, k - 60):k],
                    "after": words[k:k + 60]})
    return out


# ---------------------------------------------------------------- 打分

def _pitch_reset(track, cands: list) -> list:
    """前后 10 秒的中位基频差，单位半音。没有声轨就全给 0。"""
    if track is None:
        return [0.0] * len(cands)
    vals = []
    for c in cands:
        a = track.window(max(0, c["time"] - 10), c["time"])
        b = track.window(c["time"], c["time"] + 10)
        if a["f0_med"] > 60 and b["f0_med"] > 60:
            vals.append(abs(12 * math.log2(b["f0_med"] / a["f0_med"])))
        else:
            vals.append(0.0)
    return vals


def score(cands: list, duration: float, k: int, track=None) -> list:
    if not cands:
        return []
    gaps = np.array([c["gap"] for c in cands], dtype=float)
    # 对数标度：2.4 秒和 9.2 秒的停顿在听感上差得远，按比例封顶会把
    # 两者压成同一个 1.0，长停顿的信息就丢了
    gmax = max(1.0, float(np.percentile(gaps, 99)))
    pitches = _pitch_reset(track, cands)
    ideal = duration / max(1, k)
    goals = [ideal * j for j in range(1, k)]

    for i, c in enumerate(cands):
        pause = min(1.0, math.log1p(c["gap"]) / math.log1p(gmax))
        before, after = _content(c["before"]), _content(c["after"])
        union = before | after
        cohesion = 1 - (len(before & after) / len(union)) if union else 0.0
        reset = min(1.0, pitches[i] / 6.0)
        # 位置先验按**时间**离最近理想间距多远算。按候选下标算等于给每个
        # 候选加一条与内容无关的噪声。
        off = min(abs(c["time"] - g) for g in goals)
        prior = math.exp(-((off / (ideal * 0.6)) ** 2))
        c["score"] = round(0.30 * pause + 0.30 * cohesion +
                           0.15 * reset + 0.25 * prior, 4)
        c["py"] = {"pause": round(pause, 3), "cohesion": round(cohesion, 3),
                   "reset": round(reset, 3), "prior": round(prior, 3)}
    return cands


# ---------------------------------------------------------------- DP

def choose(cands: list, duration: float, k: int,
           min_len: float, max_len: float) -> list:
    """在候选点里选 k-1 个边界，硬约束每章长度。返回选中的候选。"""
    if k <= 1 or not cands:
        return []
    n = len(cands)
    NEG = -1e18
    dp = [[NEG] * (k + 1) for _ in range(n + 1)]
    prev = [[-1] * (k + 1) for _ in range(n + 1)]

    def ok_between(t0: float, t1: float) -> bool:
        return min_len <= (t1 - t0) <= max_len

    for i in range(n):
        if ok_between(0, cands[i]["time"]):
            dp[i][1] = cands[i]["score"]
    for j in range(2, k):
        for i in range(n):
            best, arg = NEG, -1
            for p in range(i):
                if dp[p][j - 1] == NEG:
                    continue
                if not ok_between(cands[p]["time"], cands[i]["time"]):
                    continue
                v = dp[p][j - 1] + cands[i]["score"]
                if v > best:
                    best, arg = v, p
            dp[i][j], prev[i][j] = best, arg

    best, arg = NEG, -1
    for i in range(n):
        total = dp[i][k - 1]
        if total == NEG:
            continue
        if not ok_between(cands[i]["time"], duration):
            continue
        if total > best:
            best, arg = total, i

    if arg < 0:                       # 约束太紧选不出来，就退化成等分
        return _uniform(cands, duration, k)

    picked, i, j = [], arg, k - 1
    while j >= 1 and i >= 0:
        picked.append(cands[i])
        i, j = prev[i][j], j - 1
    return sorted(picked, key=lambda c: c["time"])


def _uniform(cands, duration, k):
    goals = [duration * i / k for i in range(1, k)]
    picked, used = [], set()
    for g in goals:
        best = min((c for c in cands if id(c) not in used),
                   key=lambda c: abs(c["time"] - g), default=None)
        if best:
            used.add(id(best))
            picked.append(best)
    return sorted(picked, key=lambda c: c["time"])


# ---------------------------------------------------------------- 输出

def review_markdown(picked: list, cands: list, k: int, duration: float) -> str:
    from .config import format_time
    lines = [f"# 分章建议（目标 {k} 章，全片 {format_time(duration)}）", "",
             "算法只看得到停顿、词汇衔接、语调重置 —— 它**读不懂**这段在讲什么，",
             "所以它给出的切分点常常落在音乐的收尾、而不是话题的转折上。",
             "请你读下面每个候选点的前后文，自己决定切哪里。", "",
             "决定后写 `decision.json`：",
             "```json",
             '{"form": "book", "boundaries": [294.9, 583.1, ...], ',
             ' "titles": ["家庭、学校与好奇心", ...]}',
             "```",
             "然后 `ipa chapterize <job> --accept decision.json`。", "",
             "## 算法推荐的切点（仅供参考）", ""]
    for rank, c in enumerate(picked, 1):
        prev_t = picked[rank - 2]["time"] if rank > 1 else 0.0
        lines += [f"### {rank}. {format_time(c['time'])}　"
                  f"停顿 {c['gap']:.2f}s　分数 {c['score']:.2f}",
                  f"若切这里：本章 {format_time(prev_t)}–{format_time(c['time'])}"
                  f"（{format_time(c['time'] - prev_t)} 长）",
                  "",
                  "前：" + " ".join(w["w"].strip() for w in c["before"][-30:]),
                  "",
                  "后：" + " ".join(w["w"].strip() for w in c["after"][:30]),
                  ""]
    lines += ["## 全部候选（按时间）", "",
              "| 时间 | 秒 | 停顿 | 分数 | 前文 | 后文 |",
              "|---|---|---|---|---|---|"]
    for c in sorted(cands, key=lambda x: x["time"]):
        mark = "**" if c in picked else ""
        before = " ".join(w["w"].strip() for w in c["before"][-6:])
        after = " ".join(w["w"].strip() for w in c["after"][:6])
        lines.append(f"| {mark}{format_time(c['time'])}{mark} | {c['time']:.1f} | "
                     f"{c['gap']:.2f} | {c['score']:.2f} | {before} | {after} |")
    return "\n".join(lines)


def apply_decisions(job, decision: dict) -> list:
    """把 agent 的决策写回 job。边界吸附到最近的词间隙中点。"""
    words = [json.loads(x) for x in
             (job.data_dir / "words.jsonl").read_text(encoding="utf-8").splitlines()
             if x.strip()]
    bounds = sorted(float(x) for x in decision["boundaries"])
    edges = [0.0] + bounds + [job.duration]
    titles = decision.get("titles") or []

    chapters = []
    for i in range(len(edges) - 1):
        a, b = _snap(words, edges[i]), _snap(words, edges[i + 1])
        chapters.append({
            "id": i + 1,
            "title": titles[i] if i < len(titles) else f"第 {i + 1} 节",
            "start": round(a, 2), "end": round(b, 2),
            "text_path": "", "boundary_source": "chapterize",
            "meta": {"carry": "", "keys": "", "ask": []},
        })
    job.set_chapters(chapters)
    job.raw["form"]["kind"] = decision.get("form") or (
        form_for(job.duration)["kind"])
    return chapters


def _snap(words: list, t: float) -> float:
    """把时间点吸附到最近的词间隙中点，避免切在词中间。"""
    if not words:
        return t
    best = min(range(1, len(words)),
               key=lambda i: abs((words[i - 1]["end"] + words[i]["start"]) / 2 - t),
               default=0)
    return (words[best - 1]["end"] + words[best]["start"]) / 2 if best else 0.0
