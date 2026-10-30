# -*- coding: utf-8 -*-
"""素材体检：转写完成后立刻判断这是什么素材，再决定后面怎么走。

存在的理由很直接：一条按纪录片设计的流水线，遇到"每句念两遍、句间留白
五秒"的影子跟读材料时，会连着做错四件事——按目录时间分章、把练习留白当
成 VAD 丢词去补、按时长判成"分章全书"、给一句一个段落。这些错误都不是
精度问题，是方向问题，事后纠正的代价远大于事前测一次。

这里只做统计和判断，不改数据。`--apply` 时把结论写回 job.json。
"""
from __future__ import annotations

from collections import Counter

from . import dedupe as DD

# 判定阈值。这些是"看着像不像"的经验值，不追求精确。
SLOW_WPM = 80.0          # 低于此值视为慢速教学语速或有大量留白
REPEAT_RATIO = 0.30      # 三成以上条目重复 → 跟读结构
LONG_PAUSE_SEC = 3.0
SHORT_SENT_WORDS = 12


def _items(words, gap=LONG_PAUSE_SEC):
    return DD.split_items(words, gap)


def analyze(words: list) -> dict:
    if not words:
        return {"words": 0}
    span = words[-1]["end"] - words[0]["start"]
    speech = sum(max(0.0, w["end"] - w["start"]) for w in words)
    gaps = [b["start"] - a["end"] for a, b in zip(words, words[1:]) if b["start"] > a["end"]]

    items = _items(words)
    dups = 0
    for it in items:
        if len(it) >= DD.MIN_RUN * 2 and DD.find_duplicate(it) is not None:
            dups += 1
    item_lens = [len(it) for it in items]

    long_gaps = [g for g in gaps if g >= LONG_PAUSE_SEC]
    sorted_g = sorted(gaps)
    return {
        "words": len(words),
        "span_sec": round(span, 1),
        "speech_sec": round(speech, 1),
        "speech_ratio": round(speech / span, 3) if span else 0.0,
        "wpm": round(len(words) / span * 60, 1) if span else 0.0,
        "items": len(items),
        "item_len_median": sorted(item_lens)[len(item_lens) // 2] if item_lens else 0,
        "repeat_items": dups,
        "repeat_ratio": round(dups / len(items), 3) if items else 0.0,
        "long_pauses": len(long_gaps),
        "long_pause_share": round(sum(long_gaps) / span, 3) if span else 0.0,
        "gap_median": round(sorted_g[len(sorted_g) // 2], 2) if sorted_g else 0.0,
        "gap_p90": round(sorted_g[int(len(sorted_g) * 0.9)], 2) if sorted_g else 0.0,
    }


def verdict(a: dict) -> dict:
    """返回 {shape, headline, notes, settings}。settings 可直接并入 job.json。"""
    if not a.get("words"):
        return {"shape": "empty", "headline": "没有可分析的转写", "notes": [],
                "settings": {}}

    notes, settings = [], {}
    shadowing = a["repeat_ratio"] >= REPEAT_RATIO
    drill = a["speech_ratio"] < 0.65 and a["long_pause_share"] > 0.15
    slow = a["wpm"] < SLOW_WPM

    if shadowing:
        shape = "shadowing"
        headline = "影子跟读：每句念若干遍，句间留出跟读时间"
        notes.append(f"{a['repeat_items']}/{a['items']} 条含重复，占 "
                     f"{a['repeat_ratio']:.0%}")
        settings["asr.dedupe.enabled"] = True
        settings["render.features.map"] = False
        settings["meta.template"] = "drill"
        # 这类素材句子边界紧贴长静音，整片转写一定会在边界上串词；
        # 逐条重转能消掉（实测把"缺主语+多尾巴"修回整句）
        settings["asr.itemwise.enabled"] = True
    elif drill:
        shape = "drill"
        headline = "练习型：长段留白，句子之间有等待"
        notes.append(f"有声占比只有 {a['speech_ratio']:.0%}，"
                     f"{a['long_pauses']} 处 ≥{LONG_PAUSE_SEC:.0f} 秒的停顿")
        settings["render.features.map"] = False
    elif a["item_len_median"] >= SHORT_SENT_WORDS or not slow:
        shape = "narrative"
        headline = "叙述型：连续讲述，句子较长"
        settings["render.features.map"] = True
    else:
        shape = "mixed"
        headline = "介于叙述与练习之间：语速慢、句子短，但没有明显留白"
        settings["render.features.map"] = False

    if a["long_pauses"] >= 20 and a["speech_ratio"] < 0.7:
        # 大量长停顿且有声占比低：多半是真正的静音，补转只会白跑
        notes.append("长停顿很多且有声占比低，补空档（gapfill）大概率是空转")
        settings["asr.gapfill.enabled"] = False
    if a["gap_median"] >= 1.0:
        notes.append("句间停顿普遍偏长，正文按「每 5 句一段」分组更合适")
        settings["segment.paragraph_gap_sec"] = 9999.0
    if slow:
        notes.append(f"语速 {a['wpm']:.0f} 词/分，正常叙述是 140–160")

    return {"shape": shape, "headline": headline, "notes": notes,
            "settings": settings}


def markdown(a: dict, v: dict, applied: bool) -> str:
    L = ["# 素材体检", "", f"**{v['headline']}**", ""]
    L += ["| 指标 | 值 |", "|---|---|",
          f"| 词数 | {a['words']} |",
          f"| 时长 | {a['span_sec'] / 60:.1f} 分钟 |",
          f"| 语速 | {a['wpm']:.0f} 词/分 |",
          f"| 有声占比 | {a['speech_ratio']:.0%} |",
          f"| 停顿中位 / p90 | {a['gap_median']:.2f}s / {a['gap_p90']:.2f}s |",
          f"| ≥{LONG_PAUSE_SEC:.0f} 秒的停顿 | {a['long_pauses']} 处，"
          f"共占 {a['long_pause_share']:.0%} |",
          f"| 条目数（按长停顿切） | {a['items']} |",
          f"| 条目词数中位 | {a['item_len_median']} |",
          f"| 含重复的条目 | {a['repeat_items']}（{a['repeat_ratio']:.0%}） |",
          ""]
    if v["notes"]:
        L += ["## 看出来什么", ""] + [f"- {n}" for n in v["notes"]] + [""]
    if v["settings"]:
        title = "## 已写回 job.json" if applied else "## 建议（加 --apply 写回）"
        L += [title, ""] + [f"- `{k}` = `{val}`" for k, val in v["settings"].items()]
    return "\n".join(L)


def apply_settings(job, settings: dict) -> list:
    """把设置并进 job.raw，返回真正改变的项。"""
    changed = []
    for key, val in settings.items():
        parts = key.split(".")
        node = job.raw
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        if node.get(parts[-1]) != val:
            node[parts[-1]] = val
            changed.append(f"{key} = {val}")
    return changed
