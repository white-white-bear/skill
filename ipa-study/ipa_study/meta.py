# -*- coding: utf-8 -*-
"""章节文案：标题、承接句、关键词、回忆问题。

这是最容易"像但空心"的一层。技术标注可以做到毫厘不差，但如果每章的三个
问题都是"本章讲了什么"，产品就只剩一张音标表。所以这里不自动生成文案，
只生成**带足证据的请求包**，由 agent 写，再用 lint 拦住套话。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import tokenize as TK

BLACKLIST = [
    "本章讲述", "本章介绍", "本章主要", "接下来我们", "这部分介绍",
    "主要介绍", "我们将看到", "让我们来看",
    "this chapter", "in this section", "we will see", "let's look at",
]

TITLE_MAX = 20


_NOT_NAMES = set("""The This That These Those His Her Their Our Your Its My In On At For
From With As But However So Then When While After Before Now Here There What Which
Who Why How All Any Some More Most Other It He She They We You I And Or Not No Yes
Despite Because Since Although If""".split())


def salient(text: str, n: int = 24) -> list:
    """挑出专名和数字 —— 写具体问题时该引用的东西。

    要去掉句首大写词：每个句子开头的 "The"/"However"/"So" 也是大写，
    混进来会把真正的人名地名挤掉。
    """
    caps, nums = [], []
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9'’\-]+|\d+", text):
        tok = m.group(0)
        if tok[0].isdigit():
            if tok not in nums:
                nums.append(tok)
        elif (tok[0].isupper() and len(tok) > 2
              and tok not in _NOT_NAMES and tok not in caps):
            caps.append(tok)
    return (nums[:8] + caps)[:n]


# 两类素材要问的问题不一样。叙述有"后来呢"，练习材料没有——
# 给一串互不相干的日常句套回忆问题，只能问出"这一节讲了什么"。
ASK_GUIDE = {
    "narrative": [
        "`ask`：三个**必须回正文找细节才能答**的问题。问题里要出现本章的人名、",
        "产品名或数字，否则读者凭常识就能答，等于没问。",
    ],
    "drill": [
        "`ask`：这一节的正文是一串互不相干的句子，没有情节可回忆。别问「讲了什么」，",
        "改问**要翻回去找**的问题：",
        "  · 找表达：'表示 X 的是哪一句？它前后各是什么？'",
        "  · 找差异：'同样说 Y，这一节里出现了哪几种说法？'",
        "  · 找场景：'哪几句属于同一个场景？它们之间隔了多长？'",
        "这类问题必须引用正文里的英文词或数字，否则查无可查。",
    ],
}


def request_markdown(job, units_by_chapter: dict, words_by_chapter=None) -> str:
    from .config import format_time
    kind = job.raw.get("meta", {}).get("template") or (
        "narrative" if job.form["kind"] == "book" else "drill")
    out = ["# 章节文案待填", "",
           "每章需要四项：`title`（不超 20 字）、`carry`（一句承接上一章的话）、",
           "`keys`（三个关键词）、`ask`（三个问题）。", ""]
    out += ASK_GUIDE.get(kind, ASK_GUIDE["narrative"]) + [""]
    out += ["写完存成 meta.json：`{\"1\": {\"title\": ..., \"carry\": ..., "
            "\"keys\": ..., \"ask\": [...]}, ...}`", "",
            "lint 会拦：问题里没有任何本章出现过的专名或数字、承接句是套话、",
            "标题和承接句重复。", ""]
    for ch in job.chapters:
        units = units_by_chapter.get(ch.id)
        if not units:
            continue
        sents = [s for p in units for s in p["sents"]]
        text = " ".join(s["text"] for s in sents)
        n_words = sum(len(s["words"]) for s in sents)
        out += [f"## 第 {ch.id} 章　{format_time(ch.start)}–{format_time(ch.end)}"
                f"　{n_words} 词，{len(sents)} 句",
                "",
                "**开头三句**",
                *[f"- {s['text']}" for s in sents[:3]],
                "",
                "**结尾三句**",
                *[f"- {s['text']}" for s in sents[-3:]],
                "",
                "**可引用的人名/产品/数字**：" + "、".join(salient(text)),
                ""]
    return "\n".join(out)


def extract_tokens(text: str) -> set:
    return {TK.norm(t) for t in TK.tokenize(text) if len(t) > 2}


def lint(entry: dict, chapter_text: str, n: int) -> tuple:
    """返回 (errors, warnings)。errors 会让 --accept 拒绝写入。"""
    errs, warns = [], []
    title = (entry.get("title") or "").strip()
    carry = (entry.get("carry") or "").strip()
    keys = entry.get("keys") or ""
    ask = entry.get("ask") or []

    if not title:
        errs.append(f"第 {n} 章缺标题")
    elif len(title) > TITLE_MAX:
        warns.append(f"第 {n} 章标题 {len(title)} 字，超过 {TITLE_MAX}")

    if not carry:
        errs.append(f"第 {n} 章缺承接句")
    else:
        for bad in BLACKLIST:
            if bad in carry:
                errs.append(f"第 {n} 章承接句是套话（含「{bad}」）")
                break
        if title and carry.strip("。. ") == title.strip("。. "):
            errs.append(f"第 {n} 章承接句与标题重复")

    if isinstance(keys, str):
        n_keys = len([k for k in re.split(r"[·、,，/]", keys) if k.strip()])
    else:
        n_keys = len(keys)
    if n_keys < 3:
        warns.append(f"第 {n} 章关键词只有 {n_keys} 个")

    if len(ask) < 3:
        errs.append(f"第 {n} 章问题少于 3 条")

    chapter_tokens = extract_tokens(chapter_text)
    chapter_nums = set(re.findall(r"\d+", chapter_text))
    for i, q in enumerate(ask, 1):
        hits = extract_tokens(q) & chapter_tokens
        nums = set(re.findall(r"\d+", q)) & chapter_nums
        if not hits and not nums:
            warns.append(f"第 {n} 章问题 {i} 没有引用本章任何专名或数字，"
                         f"可能答得出来但不用回正文：" + q[:40])
    return errs, warns


def chapter_text(units) -> str:
    return " ".join(s["text"] for p in units for s in p["sents"])


def apply(job, meta: dict, units_by_chapter: dict) -> tuple:
    """把 meta 写回 job。返回 (errors, warnings, written)。"""
    errs, warns, written = [], [], 0
    for ch in job.raw.get("chapters", []):
        entry = meta.get(str(ch.get("id"))) or meta.get(ch.get("id"))
        if entry is None:
            errs.append(f"缺少第 {ch.get('id')} 章的文案")
            continue
        units = units_by_chapter.get(ch["id"])
        e, w = lint(entry, chapter_text(units) if units else "", ch["id"])
        errs += e
        warns += w
        if not e:
            ch.setdefault("meta", {}).update({
                "carry": entry.get("carry", ""),
                "keys": entry.get("keys", ""),
                "ask": list(entry.get("ask", [])),
            })
            ch["title"] = entry.get("title", ch.get("title", ""))
            written += 1
    return errs, warns, written


def load_request(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))
