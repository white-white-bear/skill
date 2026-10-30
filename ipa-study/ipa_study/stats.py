# -*- coding: utf-8 -*-
"""从标注结果里算出所有派生数字。

封面上的"12 章 · 564 句"、方法说明里的词数/命中数、音高表里的真实例子，
原来全是手写常量。换素材后手写常量必然过期，所以一律现算。
"""
from __future__ import annotations

from collections import Counter


def flatten(units) -> list:
    return [w for p in units for s in p.get("sents", []) for w in s["words"]]


def count(units) -> dict:
    ws = flatten(units)
    c = Counter()
    for w in ws:
        c["words"] += 1
        c["accent"] += 1 if w.get("accent") else 0
        c["weak"] += 1 if w.get("weak") else 0
        c["link"] += 1 if w.get("link") else 0
        c["unrel"] += 1 if w.get("unreleased") else 0
        c["elide"] += 1 if w.get("elided") else 0
        c["flap"] += 1 if w.get("flapped") else 0
        c["matched"] += 1 if w.get("asr") else 0
        c["no_time"] += 1 if w.get("start") is None else 0
        lv = w.get("level")
        if lv in ("H", "M", "L"):
            c["level_" + lv] += 1
        for sy in w.get("sylls", []):
            c["sylls"] += 1
            if sy.get("st") is not None:
                c["sylls_with_pitch"] += 1
    c["sentences"] = sum(len(p.get("sents", [])) for p in units)
    c["paragraphs"] = len(units)
    return dict(c)


def ratios(c: dict) -> dict:
    n = max(1, c.get("words", 0))
    return {k: c.get(k, 0) / n for k in
            ("accent", "weak", "link", "unrel", "elide", "flap", "matched")}


def doc_stats(job, units_by_chapter: dict) -> dict:
    """units_by_chapter: {章号: units}。返回封面与方法说明要用的全部数字。"""
    total = Counter()
    per_chapter = {}
    for n, units in units_by_chapter.items():
        c = count(units)
        per_chapter[n] = c
        total.update(c)
    total = dict(total)
    dur = job.duration
    return {
        "title": job.title,
        "kind": job.form["kind"],
        "audio_name": job.audio_source.name,
        "duration": dur,
        "duration_text": _hms(dur),
        "model": job.asr.get("model", ""),
        "chapters": len(units_by_chapter),
        "words": total.get("words", 0),
        "sentences": total.get("sentences", 0),
        "paragraphs": total.get("paragraphs", 0),
        "accent": total.get("accent", 0),
        "matched": total.get("matched", 0),
        "wpm": (total.get("words", 0) / dur * 60) if dur else 0.0,
        **{k: total.get(k, 0) for k in
           ("weak", "link", "unrel", "elide", "flap", "no_time")},
        "per_chapter": per_chapter,
        "baseline_f0": _baseline(job),
    }


def _hms(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def _baseline(job) -> float:
    v = job.raw.get("annotate", {}).get("baseline_f0")
    if v:
        return float(v)
    p = job.data_dir / "acoustics.json"
    if p.exists():
        import json
        try:
            return float(json.loads(p.read_text(encoding="utf-8")).get("base_f0", 0))
        except Exception:
            return 0.0
    return 0.0


def coverage(c: dict) -> dict:
    """标注完成度，供 qa 判断有没有"像但空心"。"""
    n = max(1, c.get("words", 0))
    return {
        "pitch_coverage": c.get("sylls_with_pitch", 0) / max(1, c.get("sylls", 0)),
        "match_rate": c.get("matched", 0) / n,
        "interpolated_rate": c.get("no_time", 0) / n,
    }
