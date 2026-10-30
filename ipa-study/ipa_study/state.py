# -*- coding: utf-8 -*-
"""阶段断点：每个阶段（或每章）落一份状态，记配置哈希与输入哈希。

判断能否跳过的规则只有一条：状态存在 + 输出还在 + 输出哈希对得上 +
当前阶段配置片段哈希没变。任何一项不成立就重跑，没有"大概没变"的中间态。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import Job, config_hash, file_hash


class State:
    def __init__(self, job: Job):
        self.job = job
        self.dir = job.data_dir / "state"

    def path(self, stage: str, chapter: int | None = None) -> Path:
        name = stage if chapter is None else f"{stage}.{chapter:02d}"
        return self.dir / f"{name}.json"

    def read(self, stage: str, chapter: int | None = None) -> dict | None:
        p = self.path(stage, chapter)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def write(self, stage: str, chapter: int | None, outputs: list,
              stats: dict | None = None) -> dict:
        rec = {
            "stage": stage,
            "chapter": chapter,
            "schema_version": 1,
            "config_hash": config_hash(self.job.stage_config(stage)),
            "outputs": {Path(o).name: file_hash(o) for o in outputs if o},
            "stats": stats or {},
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        p = self.path(stage, chapter)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return rec

    def done(self, stage: str, chapter: int | None = None,
             outputs: list | None = None) -> bool:
        """跳过条件。outputs 为 None 时只比对配置哈希。"""
        rec = self.read(stage, chapter)
        if rec is None:
            return False
        if rec.get("config_hash") != config_hash(self.job.stage_config(stage)):
            return False
        if outputs:
            for o in outputs:
                p = Path(o)
                if not p.exists():
                    return False
                if rec.get("outputs", {}).get(p.name) != file_hash(p):
                    return False
        return True

    def adopt(self, stage: str, chapter: int | None, outputs: list,
              stats: dict | None = None) -> dict:
        """--reuse：不校验配置，直接把已有输出登记为完成（用于金标准回归）。"""
        rec = {"stage": stage, "chapter": chapter, "schema_version": 1,
               "config_hash": config_hash(self.job.stage_config(stage)),
               "outputs": {Path(o).name: file_hash(o) for o in outputs if o},
               "stats": stats or {},
               "adopted": True,
               "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        p = self.path(stage, chapter)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return rec

    def matrix(self, stages: list) -> list:
        rows = []
        for s in stages:
            rec = self.read(s)
            rows.append((s, "done" if rec else "-",
                         (rec or {}).get("finished_at", "")))
        return rows

    def clear(self, stage: str) -> int:
        n = 0
        for p in self.dir.glob(f"{stage}*.json"):
            p.unlink()
            n += 1
        return n
