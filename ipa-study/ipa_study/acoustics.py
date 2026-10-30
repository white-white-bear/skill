# -*- coding: utf-8 -*-
"""Praat 声学测量：基频、强度、音节内配时。

音高、响度、时长是**实测**；弱读、连读、失爆、吞音、浊化是**规则判定**；
音节内配时在浊音段数量对不上时是**插值**。这三类在成品里必须分开说，
否则读者会把规则推出来的东西当成测量结果。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

PITCH_FLOOR, PITCH_CEIL = 75, 400
TIME_STEP = 0.01


class Track:
    def __init__(self, path):
        import parselmouth
        self.snd = parselmouth.Sound(str(path))
        self.pitch = self.snd.to_pitch(time_step=TIME_STEP,
                                       pitch_floor=PITCH_FLOOR,
                                       pitch_ceiling=PITCH_CEIL)
        self.inten = self.snd.to_intensity(time_step=TIME_STEP,
                                           minimum_pitch=PITCH_FLOOR)
        self.f0_t = self.pitch.xs()
        self.f0 = np.asarray(self.pitch.selected_array["frequency"], dtype=float)
        self.in_t = self.inten.xs()
        self.in_v = self.inten.values[0]
        # 说话人基线：整段浊音帧的中位基频
        v = self.f0[(self.f0 > 60) & (self.f0 < PITCH_CEIL)]
        self.base = float(np.median(v)) if len(v) else 120.0

    def window(self, a, b):
        m = (self.f0_t >= a) & (self.f0_t <= b)
        f0 = self.f0[m]
        voiced = f0[f0 > 60]
        mi = (self.in_t >= a) & (self.in_t <= b)
        iv = self.in_v[mi]
        iv = iv[np.isfinite(iv)]
        st = 12 * np.log2(voiced / self.base) if len(voiced) else np.array([])
        return dict(dur=b - a,
                    voiced=len(voiced) / max(1, len(f0)),
                    f0_med=float(np.median(voiced)) if len(voiced) else 0.0,
                    st_med=float(np.median(st)) if len(st) else 0.0,
                    st_max=float(np.max(st)) if len(st) else 0.0,
                    st_min=float(np.min(st)) if len(st) else 0.0,
                    int_max=float(np.max(iv)) if len(iv) else 0.0,
                    int_med=float(np.median(iv)) if len(iv) else 0.0)

    def f0_curve(self, a, b):
        m = (self.f0_t >= a) & (self.f0_t <= b)
        f0, t = self.f0[m], self.f0_t[m]
        ok = f0 > 60
        return t[ok], f0[ok]


def zscores(vals):
    a = np.array(vals, dtype=float)
    mu, sd = a.mean(), a.std()
    return (a - mu) / sd if sd > 0.5 else np.zeros_like(a)


def voice_runs(track, a, b, minlen=3):
    m = (track.f0_t >= a) & (track.f0_t <= b)
    t, v = track.f0_t[m], track.f0[m] > 60
    runs, i = [], 0
    while i < len(v):
        if not v[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(v) and v[j + 1]:
            j += 1
        if j - i + 1 >= minlen:
            runs.append((float(t[i]), float(t[j]) + TIME_STEP))
        i = j + 1
    return runs


def save_baseline(job, track) -> None:
    p = Path(job.data_dir) / "acoustics.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"base_f0": round(track.base, 1),
                             "pitch_floor": PITCH_FLOOR,
                             "pitch_ceiling": PITCH_CEIL,
                             "time_step": TIME_STEP}, indent=1), encoding="utf-8")
