# -*- coding: utf-8 -*-
"""把旧项目（steve-jobs-ipa）回灌成 job.json。

只读旧项目的产物，不运行旧脚本。章节边界取自**实际词时间**而不是 PDF 目录
（旧目录差几十秒），并且会报出章节重叠 —— 旧对齐器把 ch05 和 ch06 串了
19.76 秒，回灌时把边界收紧到不重叠，原始值记在 legacy 里留档。
"""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

from .config import Job, ensure_dir


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _extract_dict(path: Path, names: list) -> dict:
    """从源码里抠出模块级字符串字典字面量，不执行文件。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = {n: {} for n in names}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id in out:
                try:
                    out[tgt.id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    return out


def import_project(src_dir, out_path, include_data: bool = True) -> dict:
    src = Path(src_dir).resolve()
    scripts = src / "scripts"
    data = src / "data"

    meta = _load_module(scripts / "book_meta.py", "legacy_book_meta")
    chapters_meta = meta.CHAPTERS
    map_rows = [list(r) for r in meta.MAP]

    spans = _extract_dict(scripts / "build_all.py", ["SPAN"])["SPAN"]
    lex = _extract_dict(scripts / "common.py", ["MANUAL", "ACRONYM", "I_PRODUCT"])

    chapters, report = [], []
    prev_end = None
    for n in sorted(chapters_meta):
        ann = data / f"ch{n:02d}_ann.json"
        if not ann.exists():
            continue
        units = json.loads(ann.read_text(encoding="utf-8"))
        words = [w for p in units for s in p["sents"] for w in s["words"]]
        raw_start = float(words[0]["start"])
        raw_end = float(words[-1]["end"])
        start = raw_start
        if prev_end is not None and start < prev_end:
            # 重叠时削**上一章的尾巴**，不是这一章的开头：新一章的首词时间是
            # 它自己真实说出来的位置，而上一章的末词往往是插值插飞的
            over = prev_end - start
            report.append(f"第 {n} 章起点 {start:.2f}s 早于上一章终点 {prev_end:.2f}s"
                          f"（重叠 {over:.2f}s），已把上一章终点收到此处")
            chapters[-1]["legacy"]["trimmed_to"] = round(start, 2)
            chapters[-1]["end"] = round(start, 2)
        chapters.append({
            "id": n,
            "title": chapters_meta[n]["title"],
            "start": round(start, 2),
            "end": round(raw_end, 2),
            "text_path": str(data / f"ch{n:02d}_final.txt"),
            "boundary_source": "legacy",
            "meta": {
                "carry": chapters_meta[n].get("carry", ""),
                "keys": chapters_meta[n].get("keys", ""),
                "ask": chapters_meta[n].get("ask", []),
            },
            "legacy": {
                "pdf_span": list(spans.get(n, [])),
                "span_text": chapters_meta[n].get("span", ""),
                "raw_start": round(raw_start, 2),
                "raw_end": round(raw_end, 2),
            },
        })
        prev_end = raw_end

    from .audio import probe_duration
    audio_src = r"F:\text\American accent\10月27日\10月27日.mp3"
    # 时长以音频为准；最后一章结尾不等于片子结束（片尾常有十几秒字幕）
    duration = probe_duration(audio_src) or max((c["end"] for c in chapters),
                                                default=0.0)
    baseline = _baseline_f0(chapters, data)
    job = Job.new(out_path,
                  project={"title_en": "Steve Jobs", "title_zh": "史蒂夫·乔布斯",
                           "subtitle": "发音精读版", "slug": "steve-jobs"},
                  paths={"data_dir": "data", "out_dir": "out",
                         "audio_dir": "audio"},
                  audio={"source": audio_src, "duration": round(duration, 2)},
                  text={"source": "clean", "pattern": "ch{id:02d}_final.txt",
                        "punctuation": "given"},
                  form={"kind": "book"},
                  lexicon={"project": "lexicon.json"})
    job.raw["annotate"]["baseline_f0"] = round(baseline, 1)
    job.raw["chapters"] = chapters
    job.raw["render"]["content"]["map_rows"] = map_rows
    job.raw["render"]["content"]["ui_lang"] = "zh"
    job.save()

    # 专名词典外提
    lexicon = {
        "manual": {k.lower(): v for k, v in lex["MANUAL"].items()},
        "acronyms": dict(lex["ACRONYM"]),
        "products": {k.lower(): v for k, v in lex["I_PRODUCT"].items()},
    }
    lex_path = Path(out_path).parent / "lexicon.json"
    lex_path.write_text(json.dumps(lexicon, ensure_ascii=False, indent=1),
                        encoding="utf-8")

    if include_data:
        _copy_products(src, Path(out_path).parent, chapters)

    metrics = _expected_metrics(data, chapters)
    (Path(out_path).parent / "expected_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")

    return {"chapters": len(chapters), "duration": duration,
            "warnings": report, "lexicon": str(lex_path),
            "metrics": metrics}


def _expected_metrics(data: Path, chapters: list) -> dict:
    """金标准基线：L0/L1 回归逐项比对用。"""
    from . import stats as S
    total, per = {}, {}
    for c in chapters:
        f = data / f"ch{c['id']:02d}_ann.json"
        if not f.exists():
            continue
        c_unit = S.count(json.loads(f.read_text(encoding="utf-8")))
        per[str(c["id"])] = c_unit
        for k, v in c_unit.items():
            total[k] = total.get(k, 0) + v
    n = max(1, total.get("words", 0))
    return {
        "words": total.get("words", 0),
        "sentences": total.get("sentences", 0),
        "paragraphs": total.get("paragraphs", 0),
        "accent": total.get("accent", 0),
        "weak": total.get("weak", 0),
        "link": total.get("link", 0),
        "unreleased": total.get("unrel", 0),
        "elided": total.get("elide", 0),
        "flapped": total.get("flap", 0),
        "level_H": total.get("level_H", 0),
        "level_M": total.get("level_M", 0),
        "level_L": total.get("level_L", 0),
        "ratios": {k: round(total.get(k, 0) / n, 4) for k in
                   ("accent", "weak", "link", "unrel", "elide", "flap")},
        "per_chapter": per,
    }


def _baseline_f0(chapters, data: Path) -> float:
    """说话人基线：各词重读音节中位基频的整体中位数（近似 track.base）。"""
    vals = []
    for c in chapters:
        f = data / f"ch{c['id']:02d}_ann.json"
        if not f.exists():
            continue
        for p in json.loads(f.read_text(encoding="utf-8")):
            for s in p["sents"]:
                for w in s["words"]:
                    v = w.get("main_f0")
                    if v and 60 < v < 400:
                        vals.append(float(v))
    if not vals:
        return 0.0
    vals.sort()
    return vals[len(vals) // 2]


def _copy_products(src: Path, dst: Path, chapters: list) -> None:
    """把 ann json 复制进示例目录，让 skill 包自带金标准。"""
    ex_data = ensure_dir(dst / "data")
    for c in chapters:
        for suffix in ("ann.json", "final.txt"):
            f = src / "data" / f"ch{c['id']:02d}_{suffix}"
            if f.exists():
                (ex_data / f.name).write_bytes(f.read_bytes())
