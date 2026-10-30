# -*- coding: utf-8 -*-
"""音频探测与重采样。

只做重采样，绝不裁剪：ASR 用 16k、声学分析用 22.05k，两路的时长必须
对得上，差超过 0.1 秒后面所有时间戳都会错位。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


class AudioError(Exception):
    pass


def _run(cmd: list, err: bool = False) -> str:
    """err=True 时返回 stderr —— ffmpeg 的日志类滤镜（silencedetect 等）走 stderr。"""
    try:
        # 显式指定 utf-8：Windows 默认按 GBK 解码 ffmpeg 的 stderr，遇到
        # 非 ASCII 字节会直接抛 UnicodeDecodeError
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600,
                           encoding="utf-8", errors="replace")
    except FileNotFoundError as e:
        raise AudioError(f"找不到 {cmd[0]}，请确认 ffmpeg 在 PATH 上") from e
    if r.returncode != 0:
        raise AudioError(f"{cmd[0]} 失败：{r.stderr.strip()[:400]}")
    return r.stderr if err else r.stdout


def probe(path) -> dict:
    out = _run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                "-of", "json", str(path)])
    d = json.loads(out)
    fmt = d.get("format", {})
    audio = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {
        "duration": float(fmt.get("duration", 0) or 0),
        "sample_rate": int(audio.get("sample_rate", 0) or 0),
        "channels": int(audio.get("channels", 0) or 0),
        "codec": audio.get("codec_name", ""),
        "format": fmt.get("format_name", ""),
    }


def probe_duration(path) -> float:
    p = Path(path)
    if not p.exists():
        return 0.0
    try:
        return probe(p)["duration"]
    except (AudioError, json.JSONDecodeError):
        return 0.0


def to_wav(src, dst, rate: int = 16000, channels: int = 1) -> Path:
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
          "-ar", str(rate), "-ac", str(channels), str(dst)])
    return dst


def slice_wav(src, dst, start: float, dur: float, rate: int = 16000) -> Path:
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0, start):.3f}",
          "-t", f"{dur:.3f}", "-i", str(src),
          "-ar", str(rate), "-ac", "1", str(dst)])
    return dst


def check_pair(a, b, tol: float = 0.1) -> None:
    """两个重采样结果必须等长，否则时间轴对不上。"""
    da, db = probe_duration(a), probe_duration(b)
    if abs(da - db) > tol:
        raise AudioError(f"{Path(a).name}({da:.2f}s) 与 {Path(b).name}"
                         f"({db:.2f}s) 时长不符，超过 {tol}s")
