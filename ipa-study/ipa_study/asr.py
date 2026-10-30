# -*- coding: utf-8 -*-
"""转写：分块、逐词落盘、补空档。

旧实现里偏移量被写死成 OFFSET=296，和 build_all 里的 `<300`、SPAN[1] 的 308
是三份互不相等的近似值。这里改成每个 chunk 文件头部自带绝对起点，合并时
只认头部，不再有任何隐含常数。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import tokenize as TK
from .audio import slice_wav

_SIL_RE = re.compile(r"silence_(start|end):\s*(-?[\d.]+)")


# ---------------------------------------------------------------- 分块

def find_silences(wav, noise_db: int = -35, min_silence: float = 0.5) -> list:
    """用 ffmpeg 的 silencedetect 找静音区间 [(start, end)]。"""
    from .audio import _run
    out = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav), "-af",
                f"silencedetect=noise={noise_db}dB:d={min_silence}",
                "-f", "null", "-"], err=True)
    spans, cur = [], None
    for kind, val in _SIL_RE.findall(out):
        if kind == "start":
            cur = float(val)
        elif cur is not None:
            spans.append((cur, float(val)))
            cur = None
    return spans


def plan_chunks(duration: float, silences: list, target: float = 600.0,
                min_silence: float = 0.5) -> list:
    """按目标时长切块，切点吸附到最近的静音中点。

    找不到合适静音就硬切 —— 硬切只会让一个词被劈成两半，合并时按时间去重
    能救回来；而切在静音里则完全无感。
    """
    if duration <= target * 1.2:
        return [(0.0, duration)]
    mids = [(a + b) / 2 for a, b in silences if b - a >= min_silence]
    cuts, pos = [], 0.0
    while duration - pos > target * 1.2:
        goal = pos + target
        cand = [m for m in mids if pos + target * 0.5 < m < duration - 1.0]
        if not cand:
            cuts.append(goal)
            pos = goal
            continue
        cut = min(cand, key=lambda m: abs(m - goal))
        cuts.append(cut)
        pos = cut
    bounds = [0.0] + cuts + [duration]
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


# ---------------------------------------------------------------- 转写

def load_model(cfg: dict):
    from faster_whisper import WhisperModel
    return WhisperModel(cfg.get("model", "large-v3"),
                        device=cfg.get("device", "cpu"),
                        compute_type=cfg.get("compute_type", "int8"))


_LAST_MARK = {"pct": -1}


def _progress(label: str, done: float, total: float, t0: float) -> None:
    """转写过程中报进度。交互终端走单行刷新，重定向到文件时每 10% 打一行。"""
    import sys
    import time
    pct = min(1.0, done / max(total, 1e-6))
    elapsed = time.time() - t0
    eta = (elapsed / pct - elapsed) if pct > 0.02 else 0
    if sys.stdout.isatty():
        n = int(pct * 28)
        sys.stdout.write(f"\r  {label} [{'#' * n}{'-' * (28 - n)}] {pct * 100:5.1f}%"
                         f"  剩 {eta / 60:4.1f} 分")
        sys.stdout.flush()
    else:
        mark = int(pct * 10)
        if mark > _LAST_MARK["pct"]:
            _LAST_MARK["pct"] = mark
            print(f"  {label} {pct * 100:5.1f}%  已用 {elapsed / 60:.1f} 分"
                  f"  剩约 {eta / 60:.1f} 分", flush=True)


def transcribe_now(model, wav, offset: float, cfg: dict,
                   vad_filter: bool | None = None, language: str = "en",
                   total: float | None = None, label: str = "",
                   sink=None) -> list:
    """转写整段 wav，返回时间已加 offset 的词表。不落盘。

    total 给定时按已转时长大致报进度（segment 是流式产出的，够用）。
    """
    import time
    vad = cfg.get("vad", {})
    if vad_filter is None:
        vad_filter = vad.get("filter", True)
    segments, _info = model.transcribe(
        str(wav), language=language,
        beam_size=cfg.get("beam_size", 5), word_timestamps=True,
        condition_on_previous_text=False,
        vad_filter=vad_filter,
        vad_parameters={"min_silence_duration_ms": vad.get("min_silence_ms", 300)},
    )
    words, segs = [], []
    t0 = time.time()
    _LAST_MARK["pct"] = -1
    for seg in segments:
        segs.append({"start": round(offset + seg.start, 3),
                     "end": round(offset + seg.end, 3), "text": seg.text})
        for w in (seg.words or []):
            txt = w.word.strip()
            if not txt:
                continue
            rec = {"w": txt,
                   "start": round(offset + w.start, 3),
                   "end": round(offset + w.end, 3),
                   "prob": round(float(w.probability), 3)}
            words.append(rec)
            if sink:
                sink(rec)
        if total:
            _progress(label, seg.end, total, t0)
    if total:
        _progress(label, total, total, t0)
        if sys_isatty():
            print()
    transcribe_now.last_segments = segs
    return words


def sys_isatty() -> bool:
    import sys
    return sys.stdout.isatty()


def chunk_file(asr_dir: Path, n: int) -> Path:
    return asr_dir / f"chunk_{n:03d}.jsonl"


def read_chunk(path: Path) -> list:
    """读回一个已完成的块。没有 `_done` 标记的块视为未完成。"""
    words, done = [], False
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            if "_header" in d:
                continue
            if "_done" in d:
                done = True
                continue
            words.append(d)
    return words if done else []


def chunk_state(path: Path) -> dict:
    """给 watch / status 用：这个块转了多久、转到哪。"""
    if not path.exists():
        return {"exists": False}
    words, done = [], False
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            if "_header" in d:
                continue
            if "_done" in d:
                done = True
                continue
            words.append(d)
    return {"exists": True, "done": done, "words": len(words),
            "last_end": float(words[-1]["end"]) if words else 0.0}


def transcribe_chunk(model, wav, offset: float, out: Path, cfg: dict,
                     vad_filter: bool | None = None, language: str = "en",
                     total: float | None = None, label: str = "") -> list:
    """转写一个 chunk 并**逐词落盘**。

    边转边写的好处有两个：外部可以实时看到进度；中途被打断时已经转出来的
    部分还在。块末尾写 `{"_done": true}` 作完成标记 —— 没有这个标记的文件
    一律当作未完成重转，避免把半截文件当成结果。
    """
    if out.exists():
        got = read_chunk(out)
        if got:
            return got
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps({"_header": {"offset": offset,
                                        "model": cfg.get("model", "")}},
                           ensure_ascii=False) + "\n")
        f.flush()

        def sink(w):
            f.write(json.dumps(w, ensure_ascii=False) + "\n")
            f.flush()

        words = transcribe_now(model, wav, offset, cfg, vad_filter, language,
                               total=total, label=label, sink=sink)
        f.write(json.dumps({"_done": True, "words": len(words)}) + "\n")

    seg_file = out.with_suffix(".seg.jsonl")
    seg_file.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n"
                                for x in transcribe_now.last_segments),
                        encoding="utf-8")
    return words


# ---------------------------------------------------------------- 合并

def merge(chunks: list, extra: list | None = None, dedup: float = 0.35) -> list:
    """合并所有份转写。按时间排序，同词在 0.35 秒内视为重复。"""
    words = [w for c in chunks for w in c]
    if extra:
        words = words + list(extra)
    words.sort(key=lambda w: (w["start"], w["end"]))
    seen: dict = {}
    out = []
    for w in words:
        key = TK.norm(w["w"])
        if any(abs(k - w["start"]) < dedup for k in seen.get(key, [])):
            continue
        seen.setdefault(key, []).append(w["start"])
        out.append(w)
    return out


def itemwise(model, wav, words, cfg: dict, tmp_dir: Path,
             language: str = "en", gap: float = 3.0, pad: float = 0.30) -> list:
    """按长停顿切成条目，逐条单独转写。

    Whisper 在长静音边界上会把下一句的首词卡在停顿之前并拉长到填满空隙
    （实测：`I` 占 1.26 秒，"to get up" 被甩到 5 秒之后）。整片转写没法避免；
    把每条单独切出来转，边界错位就无从产生。

    代价是每条都要过一次模型；语料里条目很多时（跟读材料动辄 300 条）
    总耗时不一定更低，所以做成可选。
    """
    if not words:
        return []
    items, cur = [], [words[0]]
    for a, b in zip(words, words[1:]):
        if b["start"] - a["end"] > gap:
            items.append(cur)
            cur = []
        cur.append(b)
    items.append(cur)

    out = []
    for i, it in enumerate(items):
        a = max(0.0, it[0]["start"] - pad)
        b = it[-1]["end"] + pad
        if b - a < 0.2:
            continue
        clip = slice_wav(wav, tmp_dir / f"_item_{i:04d}.wav", a, b - a)
        out.extend(transcribe_now(model, clip, a, cfg, vad_filter=False,
                                  language=language))
        try:
            clip.unlink()
        except OSError:
            pass
    return out


def find_gaps(words: list, gap_sec: float = 3.0) -> list:
    return [(a["end"], b["start"]) for a, b in zip(words, words[1:])
            if b["start"] - a["end"] > gap_sec]


def gapfill(model, wav16, words, cfg: dict, tmp_dir: Path,
            language: str = "en") -> list:
    """对长空档关掉 VAD 重转。VAD 会把整段旁白当噪声吞掉，主转写就留下空洞。"""
    gcfg = cfg.get("gapfill", {})
    if not gcfg.get("enabled", True) or not words:
        return []
    out = []
    for i, (a, b) in enumerate(find_gaps(words, gcfg.get("gap_sec", 3.0))):
        s0 = max(0.0, a - 1.0)
        clip = slice_wav(wav16, tmp_dir / f"_gap_{i:03d}.wav", s0, (b - a) + 2.0)
        got = transcribe_now(model, clip, s0, cfg, vad_filter=False,
                             language=language)
        min_prob = gcfg.get("min_prob", 0.4)
        out += [w for w in got if w.get("prob", 1.0) >= min_prob]
    return out
