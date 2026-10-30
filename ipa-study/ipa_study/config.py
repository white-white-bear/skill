# -*- coding: utf-8 -*-
"""job.json：整条生成线唯一的事实源。

章节边界、音频路径、阈值、输出位置都只在这里定义一次。旧项目里同一件事
被写死在六个地方（build_all.SPAN、book_meta.span 字符串、asr_rest.OFFSET、
build_all 的 <300 判断、SPAN[1]、split_chapters 的正则），换素材必出串章。
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1

# 所有未在 job.json 里出现的字段都取这里的值。
DEFAULTS: dict = {
    "schema_version": SCHEMA_VERSION,
    "project": {"title_en": "", "title_zh": "", "subtitle": "发音精读版",
                "slug": "untitled", "author": ""},
    "paths": {"data_dir": "data", "out_dir": "out", "audio_dir": "audio"},
    "audio": {"source": "", "language": "en", "duration": 0.0,
              "asr_rate": 16000, "analysis_rate": 22050},
    "text": {"source": "none", "path": "", "pattern": "", "encoding": "utf-8",
             "punctuation": "auto"},
    "form": {"kind": "auto", "min_minutes": 3.0, "max_minutes": 12.0},
    "chapters": [],
    "asr": {
        "model": "large-v3", "device": "cpu", "compute_type": "int8",
        "beam_size": 5,
        "vad": {"filter": True, "min_silence_ms": 300},
        "chunk": {"target_sec": 600, "min_silence_sec": 0.5},
        "gapfill": {"enabled": True, "gap_sec": 3.0, "min_prob": 0.4},
        # 跟读教材里每句念两遍，打开就只留第一遍。演讲排比通常间隔更长，
        # 不会被误删，但仍然默认关闭——删错了最难发现。
        "dedupe": {"enabled": False, "max_gap_sec": 2.0},
        # 按长停顿切条目后逐条重转。整片转写会在长静音边界上把下一句首词
        # 卡在停顿之前，这是修那个的。代价是要多跑一遍模型。
        "itemwise": {"enabled": False, "gap": 3.0},
    },
    "align": {"mode": "auto", "band_width": 24, "window_pad_before": 18,
              "window_pad_after": 45, "interpolate_weight": "phones",
              "enforce_no_overlap": True},
    "segment": {"sentence_gap_sec": 0.60, "paragraph_gap_sec": 1.50,
                "max_sentence_words": 45, "min_sentence_words": 4},
    # 候选点要松：0.5 秒停顿就能覆盖到大多数真实章节边界，最后由 DP 和
    # agent 复核收窄。设成 1.2 秒会只剩十几个候选，最好的边界根本不在里面。
    "chapterize": {"candidate_gap_sec": 0.50, "edge_margin_sec": 30.0},
    "lexicon": {"project": "", "manual": {},
                "gate": {"max_unresolved_ratio": 0.001, "fail_frequency": 2}},
    "annotate": {"accent_threshold": 0.62, "level_semitones": 2.2,
                 "contour_semitones_per_sec": 3.5, "link_gap_sec": 0.06,
                 "calibration": "fixed", "target_accent_ratio": 0.175},
    "render": {
        "theme": {"ipa_font": "", "cjk_font": "", "page": "A4",
                  "accent_color": "#b3261e", "weak_color": "#1f5fa8",
                  "link_color": "#0f8b8d"},
        "features": {"cover": True, "map": True, "pitch_page": True,
                     "legend": True, "summary": True, "chapter_questions": True},
        "content": {"ui_lang": "zh", "methods": "auto"},
    },
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def format_time(sec: float) -> str:
    """3964 → '01:06:04'；293.3 → '04:53'。"""
    sec = max(0, int(round(sec)))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def format_span(a: float, b: float) -> str:
    return f"{format_time(a)}–{format_time(b)}"


class JobError(Exception):
    """配置错误，对应退出码 2。"""


@dataclass
class Chapter:
    id: int
    title: str = ""
    start: float = 0.0
    end: float = 0.0
    text_path: str = ""
    boundary_source: str = "manual"
    meta: dict = field(default_factory=dict)

    @property
    def carry(self) -> str:
        return self.meta.get("carry", "")

    @property
    def keys(self) -> str:
        return self.meta.get("keys", "")

    @property
    def ask(self) -> list:
        return self.meta.get("ask", [])

    @property
    def span_text(self) -> str:
        return format_span(self.start, self.end)


@dataclass
class Job:
    path: Path
    raw: dict

    # ------------------------------------------------------------ 构造
    @classmethod
    def load(cls, path) -> "Job":
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise JobError(f"找不到 job.json：{p}")
        raw = json.loads(p.read_text(encoding="utf-8"))
        return cls(p, _deep_merge(DEFAULTS, raw))

    @classmethod
    def new(cls, path, **over) -> "Job":
        p = Path(path).expanduser().resolve()
        raw = _deep_merge(DEFAULTS, over)
        raw["schema_version"] = SCHEMA_VERSION
        return cls(p, raw)

    # ------------------------------------------------------------ 路径
    @property
    def root(self) -> Path:
        return self.path.parent

    def resolve(self, value: str) -> Path:
        """相对路径一律相对 job.json 所在目录，不再依赖 CWD。"""
        if not value:
            return self.root
        q = Path(value).expanduser()
        return q if q.is_absolute() else (self.root / q).resolve()

    @property
    def data_dir(self) -> Path:
        return self.resolve(self.raw["paths"]["data_dir"])

    @property
    def out_dir(self) -> Path:
        return self.resolve(self.raw["paths"]["out_dir"])

    @property
    def audio_dir(self) -> Path:
        return self.resolve(self.paths["audio_dir"])

    @property
    def audio_source(self) -> Path:
        return self.resolve(self.raw["audio"]["source"])

    @property
    def duration(self) -> float:
        return float(self.raw["audio"]["duration"])

    # ------------------------------------------------------------ 分节访问
    @property
    def paths(self) -> dict:
        return self.raw["paths"]

    @property
    def project(self) -> dict:
        return self.raw["project"]

    @property
    def asr(self) -> dict:
        return self.raw["asr"]

    @property
    def align(self) -> dict:
        return self.raw["align"]

    @property
    def segment(self) -> dict:
        return self.raw["segment"]

    @property
    def annotate_cfg(self) -> dict:
        return self.raw["annotate"]

    @property
    def render_cfg(self) -> dict:
        return self.raw["render"]

    @property
    def lexicon_cfg(self) -> dict:
        return self.raw["lexicon"]

    @property
    def form(self) -> dict:
        return self.raw["form"]

    @property
    def text(self) -> dict:
        return self.raw["text"]

    @property
    def chapters(self) -> list:
        return [Chapter(id=c["id"], title=c.get("title", ""),
                        start=float(c.get("start", 0.0)),
                        end=float(c.get("end", 0.0)),
                        text_path=c.get("text_path", ""),
                        boundary_source=c.get("boundary_source", "manual"),
                        meta=c.get("meta", {}))
                for c in self.raw["chapters"]]

    def chapter(self, n: int) -> Chapter:
        for c in self.chapters:
            if c.id == n:
                return c
        raise JobError(f"没有第 {n} 章")

    def chapter_file(self, n: int, suffix: str) -> Path:
        return self.data_dir / f"ch{n:02d}_{suffix}"

    @property
    def title(self) -> str:
        p = self.project
        return f"{p['title_en']} {p['subtitle']}".strip() if p["title_en"] \
            else f"{p['title_zh']} {p['subtitle']}".strip()

    # ------------------------------------------------------------ 写回
    def save(self, path=None) -> Path:
        target = Path(path) if path else self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.raw, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        return target

    def set_chapters(self, chapters: list) -> None:
        """chapters 形如 [{id,title,start,end,...}]，写回前做完整性检查。"""
        self.raw["chapters"] = chapters

    # ------------------------------------------------------------ 校验
    def validate(self, strict_meta: bool = False) -> list:
        """返回错误列表；空列表即通过。"""
        errs: list = []
        chs = self.raw.get("chapters") or []

        if not chs:
            errs.append("chapters 为空")
            return errs
        if self.form["kind"] == "book" and len(chs) < 3:
            errs.append(f"kind=book 但只有 {len(chs)} 章")

        dur = self.duration
        prev = None
        for c in chs:
            start, end = float(c.get("start", 0)), float(c.get("end", 0))
            tag = f"第 {c.get('id')} 章"
            if end <= start:
                errs.append(f"{tag} 结束时间 {end} 不晚于开始时间 {start}")
            if start < -0.5:
                errs.append(f"{tag} 起点 {start} 早于 0")
            if dur and end > dur + 1.0:
                errs.append(f"{tag} 终点 {end} 超出音频时长 {dur:.1f}")
            if prev is not None:
                overlap = float(prev.get("end", 0)) - start
                if overlap > 0.5:
                    errs.append(f"第 {prev.get('id')} 章与{tag}重叠 {overlap:.2f} 秒")
                if start < float(prev.get("start", 0)):
                    errs.append(f"{tag} 没有按时间排序")
            prev = c

        if strict_meta:
            for c in chs:
                m = c.get("meta") or {}
                if not c.get("title"):
                    errs.append(f"第 {c.get('id')} 章缺标题")
                if self.form["kind"] in ("book", "sections") and len(m.get("ask", [])) < 3:
                    errs.append(f"第 {c.get('id')} 章回忆问题少于 3 条")
        return errs

    def require_valid(self, strict_meta: bool = False) -> None:
        errs = self.validate(strict_meta=strict_meta)
        if errs:
            raise JobError("配置校验失败：\n  - " + "\n  - ".join(errs))

    # ------------------------------------------------------------ 哈希
    def stage_config(self, stage: str) -> dict:
        """某阶段只对自己消费的字段取哈希：改章节标题不该让 asr 失效。"""
        owned = {
            "prep": ["audio", "paths"],
            "asr": ["asr", "audio", "paths"],
            "chapterize": ["chapterize", "audio"],
            "segment": ["segment", "text"],
            "align": ["align", "segment"],
            "lexicon": ["lexicon"],
            "annotate": ["annotate", "lexicon"],
            "meta": ["form", "project"],
            "render": ["render", "project", "form"],
            "qa": [],
        }.get(stage)
        if owned is None:
            return {"raw": self.raw}
        return {k: self.raw.get(k) for k in owned}


def config_hash(obj) -> str:
    import hashlib
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def file_hash(path) -> str:
    import hashlib
    p = Path(path)
    if not p.exists():
        return ""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def ensure_dir(p) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p
