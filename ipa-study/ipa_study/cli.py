# -*- coding: utf-8 -*-
"""命令行入口。

每个阶段一个子命令，都可以单独重跑；`run` 把它们串起来。
闸门失败时返回非零码而不是抛栈，让 agent 知道该停下来做什么。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import Job, JobError

# 退出码约定
OK, CONFIG_ERROR = 0, 2
GATE_CHAPTERIZE, GATE_SEGMENT, GATE_LEXICON, GATE_ALIGN, GATE_QA = 10, 11, 12, 13, 14


def _err(msg: str, code: int = CONFIG_ERROR) -> int:
    print(f"错误：{msg}", file=sys.stderr)
    return code


# ---------------------------------------------------------------- import-legacy

def cmd_import_legacy(a) -> int:
    from .import_legacy import import_project
    try:
        r = import_project(a.src, a.out, include_data=not a.no_data)
    except Exception as e:
        return _err(f"回灌失败：{e}")
    print(f"已生成 {a.out}：{r['chapters']} 章，时长 {r['duration']:.1f}s")
    print(f"专名词典 → {r['lexicon']}")
    for w in r["warnings"]:
        print(f"  ! {w}")
    return OK


# ---------------------------------------------------------------- 只读命令

def cmd_validate(a) -> int:
    job = Job.load(a.job)
    errs = job.validate(strict_meta=a.strict)
    if not errs:
        print("配置通过")
        return OK
    for e in errs:
        print(f"  - {e}")
    return CONFIG_ERROR


def _bar(pct: float, width: int = 32) -> str:
    n = int(max(0.0, min(1.0, pct)) * width)
    return "#" * n + "-" * (width - n)


def asr_progress(job) -> dict | None:
    """按**已转出的最后一个词的时间**算进度。

    不能用块的起点算：块的起点和上一块重叠，会把进度少算掉一整块；
    也不能只数完成的块，那样块内就没有进度可看。
    """
    from .asr import chunk_state
    asr_dir = job.data_dir / "asr"
    if not asr_dir.exists():
        return None
    plan_p = asr_dir / "plan.json"
    if not plan_p.exists():
        return None
    plan = json.loads(plan_p.read_text(encoding="utf-8"))["chunks"]
    done_sec, words, finished = 0.0, 0, 0
    for i, _span in enumerate(plan):
        st = chunk_state(asr_dir / f"chunk_{i:03d}.jsonl")
        if not st["exists"]:
            continue
        words += st["words"]
        done_sec = max(done_sec, st["last_end"])
        if st["done"]:
            finished += 1
    total = job.duration or float(json.loads(
        plan_p.read_text(encoding="utf-8")).get("total", 0)) or done_sec
    return {"chunks_done": finished, "chunks_total": len(plan),
            "words": words, "done_sec": done_sec, "total": total}


def cmd_watch(a) -> int:
    """实时进度条。在终端里跑，每 2 秒刷新一次。"""
    import sys
    import time
    job = Job.load(a.job)
    tty = sys.stdout.isatty()
    try:
        while True:
            p = asr_progress(job)
            if p is None:
                print("还没有开始转写")
                return OK
            pct = p["done_sec"] / max(1e-6, p["total"])
            line = (f"[{_bar(pct)}] {pct * 100:5.1f}%  "
                    f"{p['done_sec'] / 60:5.1f}/{p['total'] / 60:.1f} 分钟  "
                    f"{p['words']} 词  块 {p['chunks_done']}/{p['chunks_total']}")
            if tty:
                sys.stdout.write("\r" + line + "   ")
                sys.stdout.flush()
            else:
                print(line, flush=True)
            if p["chunks_done"] >= p["chunks_total"]:
                if tty:
                    print()
                print("转写完成")
                return OK
            if getattr(a, "once", False):
                return OK
            time.sleep(a.interval)
    except KeyboardInterrupt:
        if tty:
            print()
        return OK


def cmd_status(a) -> int:
    from .state import State
    job = Job.load(a.job)
    st = State(job)
    stages = ["prep", "asr", "chapterize", "segment", "align",
              "lexicon", "annotate", "meta", "render", "qa"]
    for name, status, when in st.matrix(stages):
        print(f"{name:<12} {status:<6} {when}")

    prog = asr_progress(job)
    if prog and not st.done("asr"):
        pct = prog["done_sec"] / max(1e-6, prog["total"])
        print(f"\n转写中 [{_bar(pct)}] {pct * 100:5.1f}%")
        print(f"  已完成 {prog['chunks_done']} 块 · 音频 "
              f"{prog['done_sec'] / 60:.1f}/{prog['total'] / 60:.1f} 分钟 · "
              f"{prog['words']} 词")
    return OK


def cmd_fonts(a) -> int:
    from . import fonts
    job = Job.load(a.job) if a.job else None
    theme = job.render_cfg["theme"] if job else {}
    print(fonts.report(theme))
    return OK


# ---------------------------------------------------------------- render

def _load_units(job: Job) -> dict:
    out = {}
    for ch in job.chapters:
        p = job.data_dir / f"ch{ch.id:02d}_ann.json"
        if p.exists():
            out[ch.id] = json.loads(p.read_text(encoding="utf-8"))
    return out


def cmd_render(a) -> int:
    from . import stats
    from .render import build_book, build_single
    from .config import ensure_dir

    job = Job.load(a.job)
    job.require_valid()

    units = _load_units(job)
    if not units:
        return _err(f"{job.data_dir} 下没有 chNN_ann.json，先跑 annotate")

    only = None
    if a.chapters:
        only = {int(x) for x in a.chapters.split(",")}
        units = {k: v for k, v in units.items() if k in only}
        if not units:
            return _err(f"指定的章没有标注结果：{a.chapters}")

    s = stats.doc_stats(job, units)
    out = Path(a.out) if a.out else (job.out_dir / f"{job.project['slug']}.pdf")
    ensure_dir(out.parent)

    kind = job.form["kind"]
    is_short = (job.duration and job.duration < 12 * 60)
    if kind == "single" or (kind == "auto" and is_short) or a.chapters and len(units) == 1:
        if only is None or len(units) == 1:
            units_one = next(iter(units.values()))
            build_single(job, units_one, s, out)
        else:
            build_book(job, units, s, out, only=only)
    elif only is not None:
        build_book(job, units, s, out, only=only)
    else:
        build_book(job, units, s, out)

    print(f"已输出 {out}（{s['chapters']} 章 · {s['sentences']} 句 · {s['words']} 词）")
    return OK


# ---------------------------------------------------------------- init

def cmd_init(a) -> int:
    from . import audio, chapterize as CZ
    from pathlib import Path as P

    src = P(a.audio).expanduser().resolve()
    if not src.exists():
        return _err(f"音频不存在：{src}")
    dur = audio.probe_duration(src)
    if dur <= 0:
        return _err("ffprobe 读不出时长")

    form = CZ.form_for(dur)
    title = a.title or src.stem
    chapters = []
    if form["kind"] == "single":
        # 单篇也建一章：后面 align/render 都按 chapters 走，不留特例
        chapters = [{"id": 1, "title": title, "start": 0.0, "end": round(dur, 2),
                     "text_path": "", "boundary_source": "form",
                     "meta": {"carry": "", "keys": "", "ask": []}}]

    job = Job.new(a.out,
                  project={"title_en": a.title_en or "", "title_zh": title,
                           "subtitle": "发音精读版",
                           "slug": src.stem.replace(" ", "-").lower()},
                  audio={"source": str(src), "duration": round(dur, 2),
                         "language": a.language},
                  text={"source": "clean" if a.text else "none"},
                  form={"kind": form["kind"] if form["kind"] != "sections" else "sections"},
                  lexicon={"project": "lexicon.json"})
    job.raw["chapters"] = chapters
    job.save()

    print(f"音频 {dur:.1f}s（{dur / 60:.1f} 分钟）→ 形态 {form['kind']}，"
          f"目标 {form['k']} 章")
    if form["kind"] != "single":
        print("  下一步：ipa prep → ipa asr → ipa chapterize（在那里定章边界）")
    print(f"已写入 {a.out}")
    return OK


# ---------------------------------------------------------------- prep / asr

def _wavs(job):
    return (job.audio_dir / "full_16k.wav", job.audio_dir / "full_22k.wav")


def cmd_prep(a) -> int:
    from . import audio
    from .config import ensure_dir
    job = Job.load(a.job)
    src = job.audio_source
    if not src.exists():
        return _err(f"音频不存在：{src}")
    dur = audio.probe_duration(src)
    if dur <= 0:
        return _err("ffprobe 读不出时长")
    ensure_dir(job.audio_dir)
    w16, w22 = _wavs(job)
    audio.to_wav(src, w16, rate=int(job.raw["audio"]["asr_rate"]))
    audio.to_wav(src, w22, rate=int(job.raw["audio"]["analysis_rate"]))
    # 两路必须等长，否则 ASR 时间戳与声学测量对不上
    audio.check_pair(w16, w22)
    if abs(job.raw["audio"].get("duration", 0) - dur) > 0.5:
        job.raw["audio"]["duration"] = round(dur, 2)
        job.save()
    print(f"音频 {dur:.1f}s → {w16.name} / {w22.name}")
    return OK


def cmd_asr(a) -> int:
    from . import asr
    from .state import State
    job = Job.load(a.job)
    w16, _ = _wavs(job)
    if not w16.exists():
        return _err("先跑 prep")
    asr_dir = job.data_dir / "asr"
    asr_dir.mkdir(parents=True, exist_ok=True)

    dur = job.duration or 0
    sil = asr.find_silences(w16)
    cc = job.asr.get("chunk", {})
    plan = asr.plan_chunks(dur, sil, float(cc.get("target_sec", 600)),
                           float(cc.get("min_silence_sec", 0.5)))
    # 把分块计划落盘：转写进程之外（watch / status）要靠它算进度，
    # 否则只能数"已有几个块文件"，永远算不出还剩几块
    (asr_dir / "plan.json").write_text(json.dumps(
        {"total": dur, "chunks": plan}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"分 {len(plan)} 块：" + ", ".join(f"{s:.0f}–{e:.0f}" for s, e in plan),
          flush=True)

    model = asr.load_model(job.asr)
    chunks = []
    for i, (s, e) in enumerate(plan):
        out = asr.chunk_file(asr_dir, i)
        if out.exists():
            print(f"  chunk {i} 已完成，跳过")
        else:
            clip = asr_dir / f"_clip_{i:03d}.wav"
            from .audio import slice_wav
            slice_wav(w16, clip, s, e - s)
            print(f"  chunk {i}: {s:.0f}–{e:.0f} …", flush=True)
        chunks.append(asr.transcribe_chunk(model, asr_dir / f"_clip_{i:03d}.wav",
                                           s, out, job.asr,
                                           language=job.raw["audio"]["language"],
                                           total=e - s,
                                           label=f"chunk {i + 1}/{len(plan)}"))
    words = asr.merge(chunks)

    iw = job.asr.get("itemwise", {})
    if iw.get("enabled"):
        # 整片转写在长静音边界上会把下一句首词卡在停顿之前；切成条目逐条重转
        # 就不会。代价是再过一遍模型，所以只在 profile 判断需要时才开。
        print(f"逐条重转 {len(words)} 词，可能需要一些时间 …", flush=True)
        words = asr.itemwise(model, w16, words, job.asr, asr_dir,
                             language=job.raw["audio"]["language"],
                             gap=float(iw.get("gap", 3.0)))
        words = asr.merge([words])

    gaps = asr.find_gaps(words, job.asr["gapfill"].get("gap_sec", 3.0))
    if gaps:
        print(f"发现 {len(gaps)} 处 >{job.asr['gapfill'].get('gap_sec', 3)}s 空档，补转")
        extra = asr.gapfill(model, w16, words, job.asr, asr_dir,
                            language=job.raw["audio"]["language"])
        words = asr.merge([words], extra)

    (job.data_dir / "words.jsonl").write_text(
        "".join(json.dumps(w, ensure_ascii=False) + "\n" for w in words),
        encoding="utf-8")
    State(job).write("asr", None, [job.data_dir / "words.jsonl"],
                     stats={"words": len(words), "chunks": len(plan)})
    span = (words[-1]["end"] - words[0]["start"]) if words else 0
    print(f"共 {len(words)} 词，{len(words) / max(1, span):.2f} 词/秒")
    return OK


def _load_words(job) -> list:
    p = job.data_dir / "words.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# ---------------------------------------------------------------- segment / align

def cmd_segment(a) -> int:
    from . import segment, stats
    job = Job.load(a.job)
    words = _load_words(job)
    if not words:
        return _err("没有 words.jsonl，先跑 asr")
    if job.text.get("source") == "clean":
        print("正文已是校订稿，跳过整理")
        return OK

    all_review, problems = {}, 0
    for ch in job.chapters:
        window = [w for w in words if ch.start - 0.5 <= w["start"] <= ch.end + 0.5]
        if not window:
            continue
        norm_words, glued = segment.normalise_words(window)
        sents = segment.build_sentences(norm_words, job.segment)
        paras = segment.group_paragraphs(sents, job.segment)
        text = segment.capitalise(segment.render_text(paras))
        segment.write_text(job.data_dir / f"ch{ch.id:02d}_final.txt", text)
        rep = segment.review(paras, glued, job.segment)
        all_review[str(ch.id)] = rep
        problems += rep["needs_review"]

    (job.data_dir / "segment").mkdir(parents=True, exist_ok=True)
    (job.data_dir / "segment" / "review.json").write_text(
        json.dumps(all_review, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, r in all_review.items():
        print(f"  第 {k} 章：粘词 {len(r['glued'])}，未拆 {len(r['unsplit'])}，"
              f"超长句 {len(r['too_long'])}")
    print(f"草稿已写入 chNN_final.txt，请人工/agent 校对后继续")
    return GATE_SEGMENT if problems else OK


def cmd_align(a) -> int:
    from . import align, segment
    from .state import State
    job = Job.load(a.job)
    words = _load_words(job)
    if not words:
        return _err("没有 words.jsonl，先跑 asr")

    diags, total_words, total_miss = {}, 0, 0
    for ch in job.chapters:
        path = job.data_dir / f"ch{ch.id:02d}_final.txt"
        paras = segment.load_text(path)
        if not paras:
            print(f"  第 {ch.id} 章缺 ch{ch.id:02d}_final.txt，跳过")
            continue
        res = align.build_chapter(job, ch, paras, words)
        json.dump(res["units"],
                  open(job.data_dir / f"ch{ch.id:02d}_units.json", "w",
                       encoding="utf-8"), ensure_ascii=False, indent=1)
        d = res["diag"]
        diags[str(ch.id)] = d
        total_words += d["words"]
        total_miss += d["unmatched"]
        print(f"  第 {ch.id:02d} 章 {d['mode']:<11} 词 {d['words']:5d} "
              f"未匹配 {d['unmatched']:4d} ({d['unmatched_ratio']:.1%})")
    ratio = total_miss / max(1, total_words)
    (job.data_dir / "align").mkdir(parents=True, exist_ok=True)
    (job.data_dir / "align" / "report.json").write_text(
        json.dumps(diags, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"合计未匹配 {ratio:.2%}")
    return GATE_ALIGN if ratio > 0.02 else OK


# ---------------------------------------------------------------- annotate

def cmd_annotate(a) -> int:
    from . import annotate, acoustics
    from .state import State
    job = Job.load(a.job)
    _, w22 = _wavs(job)
    if not w22.exists():
        return _err("先跑 prep")

    track = acoustics.Track(w22)
    acoustics.save_baseline(job, track)
    print(f"说话人基线 {track.base:.1f} Hz")

    targets = a.chapters.split(",") if getattr(a, "chapters", None) else None
    for ch in job.chapters:
        if targets and str(ch.id) not in targets:
            continue
        p = job.data_dir / f"ch{ch.id:02d}_units.json"
        if not p.exists():
            continue
        units = json.loads(p.read_text(encoding="utf-8"))
        annotate.annotate(units, track, job.annotate_cfg)
        out = job.data_dir / f"ch{ch.id:02d}_ann.json"
        json.dump(units, open(out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        ws = [w for pp in units for s in pp["sents"] for w in s["words"]]
        tr = annotate.timing_report(units)
        print(f"  第 {ch.id:02d} 章 词 {len(ws):5d} 强读 {sum(w['accent'] for w in ws):4d}"
              f" · 摊分配时 {tr['distributed_ratio']:.1%}")
        State(job).write("annotate", ch.id, [out])
    job.raw["annotate"]["baseline_f0"] = round(track.base, 1)
    job.save()
    return OK


# ---------------------------------------------------------------- lexicon

def cmd_lexicon(a) -> int:
    from . import lexicon as LX
    job = Job.load(a.job)
    # configure() 会清空旧词表，所以两份来源必须一次性传入
    project_lex = {}
    if job.lexicon_cfg.get("project"):
        project_lex = LX.load_project_lexicon(
            job.resolve(job.lexicon_cfg["project"]))
    LX.configure(project_lex, job.lexicon_cfg.get("manual") or {})

    texts = []
    for ch in job.chapters:
        p = job.data_dir / f"ch{ch.id:02d}_final.txt"
        if p.exists():
            texts.append(p.read_text(encoding="utf-8"))
    if not texts:
        return _err("没有 chNN_final.txt")
    from . import phonology as P
    from .tokenize import tokenize
    n = 0
    for t in texts:
        for w in tokenize(t):
            # 检查实际拿去查词典的形式：1976 会先展开成 nineteen seventy-six
            for spoken in P.spoken_variants(w):
                n += 1
                LX.lookup(spoken)

    unresolved = LX.unresolved_report(int(job.lexicon_cfg["gate"].get("fail_frequency", 2)))
    ratio = sum(c for _, c in unresolved) / max(1, n)
    patch = {"manual": {}, "acronyms": {}, "products": {}}
    (job.data_dir / "lexicon").mkdir(parents=True, exist_ok=True)
    (job.data_dir / "lexicon" / "report.json").write_text(json.dumps(
        {"unresolved": unresolved, "ratio": round(ratio, 5),
         "tokens": n}, ensure_ascii=False, indent=1), encoding="utf-8")
    (job.data_dir / "lexicon" / "patch.json").write_text(
        json.dumps(patch, ensure_ascii=False, indent=1), encoding="utf-8")

    limit = float(job.lexicon_cfg["gate"].get("max_unresolved_ratio", 0.001))
    if not unresolved:
        print("词典覆盖完整")
        return OK
    print(f"未解析 {len(unresolved)} 个词形，占 {ratio:.3%}（上限 {limit:.1%}）")
    for w, c in unresolved[:25]:
        print(f"  {w:<20} ×{c}")
    print(f"补录模板：{job.data_dir / 'lexicon' / 'patch.json'}")
    return GATE_LEXICON if ratio > limit else OK


# ---------------------------------------------------------------- profile

def cmd_profile(a) -> int:
    from . import profile
    job = Job.load(a.job)
    src = job.data_dir / "words_raw.jsonl"
    if not src.exists():
        src = job.data_dir / "words.jsonl"
    if not src.exists():
        return _err("没有转写结果，先跑 asr")

    words = [json.loads(x) for x in src.read_text(encoding="utf-8").splitlines()
             if x.strip()]
    stats = profile.analyze(words)
    v = profile.verdict(stats)

    out = job.data_dir / "profile"
    out.mkdir(parents=True, exist_ok=True)
    changed = []
    if a.apply and v["settings"]:
        changed = profile.apply_settings(job, v["settings"])
        job.save()
    (out / "report.md").write_text(
        profile.markdown(stats, v, bool(changed)), encoding="utf-8")

    print(f"素材形态：{v['shape']} —— {v['headline']}")
    print(f"  语速 {stats['wpm']:.0f} 词/分 · 有声 {stats['speech_ratio']:.0%}"
          f" · {stats['items']} 条 · 重复 {stats['repeat_ratio']:.0%}")
    for n in v["notes"]:
        print(f"  · {n}")
    if changed:
        print("已写回 job.json：")
        for c in changed:
            print(f"  - {c}")
    elif v["settings"]:
        print("建议（加 --apply 写回）：")
        for k, val in v["settings"].items():
            print(f"  - {k} = {val}")
    print(f"报告：{out / 'report.md'}")
    return OK


# ---------------------------------------------------------------- dedupe

def cmd_dedupe(a) -> int:
    from . import dedupe
    job = Job.load(a.job)
    src = job.data_dir / "words.jsonl"
    if not src.exists():
        return _err("没有 words.jsonl，先跑 asr")

    backup = job.data_dir / "words_raw.jsonl"
    if not backup.exists():          # 原始版本留一份，删错了还能回来
        backup.write_bytes(src.read_bytes())

    words = [json.loads(x) for x in backup.read_text(encoding="utf-8").splitlines()
             if x.strip()]
    cfg = job.raw["asr"].get("dedupe", {})
    method = cfg.get("method", "items")

    if method == "ngram":
        kept, removed, detail = dedupe.apply(
            words, float(cfg.get("max_gap_sec", 2.0)))
        report = {"method": "ngram", "duplicates": len(detail),
                  "detail": detail}
    else:
        kept, removed, report = dedupe.apply_items(
            words, float(cfg.get("item_gap_sec", dedupe.ITEM_GAP_SEC)))
        report["method"] = "items"

    src.write_text("".join(json.dumps(w, ensure_ascii=False) + "\n" for w in kept),
                   encoding="utf-8")
    out = job.data_dir / "dedupe"
    out.mkdir(parents=True, exist_ok=True)
    report.update(kept=len(kept), removed=len(removed),
                  removed_sec=round(sum(w["end"] - w["start"] for w in removed), 1))
    report["samples"] = report.pop("detail", [])[:20]
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    if not report["duplicates"]:
        print("没有发现整句重复")
        return OK
    print(f"{report.get('items', '')} 条 → 判定重复 {report['duplicates']} 处，"
          f"删掉 {len(removed)} 词，保留 {len(kept)} 词")
    for d in report["samples"][:5]:
        if "first" in d:
            print(f"  [{d['start'] / 60:5.1f} 分] 保留: {d['first'][:52]}")
            print(f"                   丢弃: {d['dropped'][:52]}")
    print(f"明细：{out / 'report.json'}")
    return OK


# ---------------------------------------------------------------- chapterize / meta

def cmd_chapterize(a) -> int:
    from . import chapterize as CZ
    job = Job.load(a.job)
    words = _load_words(job)
    if not words:
        return _err("没有 words.jsonl，先跑 asr")

    if a.accept:
        decision = json.loads(Path(a.accept).read_text(encoding="utf-8"))
        chapters = CZ.apply_decisions(job, decision)
        errs = job.validate()
        if errs:
            return _err("分章结果不合法：\n  - " + "\n  - ".join(errs))
        job.save()
        print(f"已写入 {len(chapters)} 章")
        for c in chapters:
            print(f"  {c['id']:2d}  {c['start']:7.1f}–{c['end']:7.1f}  {c['title']}")
        return OK

    dur = job.duration or words[-1]["end"]
    form = CZ.form_for(dur, n_words=len(words))
    cands = CZ.candidates(words, job.raw["chapterize"], dur)
    if not cands:
        return _err("找不到足够的停顿候选点")

    track = None
    w22 = _wavs(job)[1]
    if w22.exists() and not a.no_pitch:
        from . import acoustics
        print("分析语调重置 …", flush=True)
        track = acoustics.Track(w22)
    CZ.score(cands, dur, form["k"], track)

    # 章节长度差异很大（这部片子从 3.5 分钟到 6 分钟都有），约束要松到
    # 能容纳最短的那一章，否则 DP 会把边界推到节奏对的地方之外
    min_len = max(60.0, 0.40 * dur / form["k"])
    max_len = max(3 * min_len, 2.0 * dur / form["k"])
    picked = CZ.choose(cands, dur, form["k"], min_len, max_len)

    out_dir = job.data_dir / "chapterize"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "candidates.json").write_text(json.dumps(
        {"duration": dur, "form": form, "picked": picked,
         "all": [{k: v for k, v in c.items() if k not in ("before", "after")}
                 for c in cands]}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "review.md").write_text(
        CZ.review_markdown(picked, cands, form["k"], dur), encoding="utf-8")

    print(f"形态 {form['kind']}，目标 {form['k']} 章，{len(cands)} 个候选点")
    for i, c in enumerate(picked, 1):
        print(f"  {i:2d}. {c['time']:7.1f}s  停顿 {c['gap']:.2f}s  分数 {c['score']:.2f}")
    print(f"复核包：{out_dir / 'review.md'}")
    return GATE_CHAPTERIZE


def cmd_meta(a) -> int:
    from . import meta as M
    job = Job.load(a.job)
    units = _load_units(job)
    if not units:
        return _err("没有标注结果，先跑 annotate")

    if a.accept:
        data = M.load_request(a.accept)
        errs, warns, written = M.apply(job, data, units)
        for w in warns:
            print(f"  提醒：{w}")
        if errs:
            for e in errs:
                print(f"  错误：{e}")
            return CONFIG_ERROR
        job.save()
        print(f"已写入 {written} 章文案")
        return OK

    out = job.data_dir / "meta"
    out.mkdir(parents=True, exist_ok=True)
    (out / "request.md").write_text(M.request_markdown(job, units), encoding="utf-8")
    print(f"请求包：{out / 'request.md'}")
    return GATE_CHAPTERIZE


# ---------------------------------------------------------------- run

STAGES = ["prep", "asr", "profile", "dedupe", "chapterize", "segment", "align",
          "lexicon", "annotate", "meta", "render", "qa"]


def cmd_run(a) -> int:
    from .config import ensure_dir
    job = Job.load(a.job)
    ensure_dir(job.data_dir)
    order = STAGES
    lo = order.index(a.from_) if a.from_ else 0
    hi = order.index(a.to) if a.to else len(order) - 1

    for st in order[lo:hi + 1]:
        print(f"\n=== {st} ===")
        sub = argparse.Namespace(job=a.job, chapters=None, only=None, out=None,
                                 accept=None, pdf=None, strict=False,
                                 no_pitch=False, apply=True, once=False,
                                 interval=2.0)
        fn = {"prep": cmd_prep, "asr": cmd_asr, "profile": cmd_profile,
              "dedupe": cmd_dedupe, "chapterize": cmd_chapterize,
              "segment": cmd_segment, "align": cmd_align,
              "lexicon": cmd_lexicon, "annotate": cmd_annotate,
              "meta": cmd_meta, "render": cmd_render, "qa": cmd_qa}[st]
        code = fn(sub)
        if code != OK:
            print(f"\n在「{st}」停下（退出码 {code}）。处理完后从这一阶段继续：")
            print(f"  ipa {st} \"{a.job}\"")
            return code
    return OK


# ---------------------------------------------------------------- qa

def cmd_qa(a) -> int:
    from . import qa
    job = Job.load(a.job)
    units = _load_units(job)
    if not units:
        return _err("没有可验收的标注结果")
    pdf = Path(a.pdf) if a.pdf else next(
        (p for p in sorted(job.out_dir.glob("*.pdf"))), None)
    rep = qa.run(job, units, pdf)
    print(json.dumps({k: v for k, v in rep.items()}, ensure_ascii=False, indent=2))
    return OK if not rep["problems"] else GATE_QA


# ---------------------------------------------------------------- 入口

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ipa", description="逐词行间注发音精读生成线")
    p.add_argument("--version", action="version", version=f"ipa-study {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("import-legacy", help="把旧项目回灌成 job.json")
    q.add_argument("--src", required=True)
    q.add_argument("--out", required=True)
    q.add_argument("--no-data", action="store_true", help="不复制标注结果")
    q.set_defaults(func=cmd_import_legacy)

    q = sub.add_parser("validate", help="校验 job.json")
    q.add_argument("job")
    q.add_argument("--strict", action="store_true", help="同时检查章节文案")
    q.set_defaults(func=cmd_validate)

    q = sub.add_parser("status", help="打印各阶段完成情况")
    q.add_argument("job")
    q.set_defaults(func=cmd_status)

    q = sub.add_parser("fonts", help="检查字体与缺字")
    q.add_argument("job", nargs="?")
    q.set_defaults(func=cmd_fonts)

    q = sub.add_parser("qa", help="验收检查")
    q.add_argument("job")
    q.add_argument("--pdf")
    q.set_defaults(func=cmd_qa)

    q = sub.add_parser("render", help="排版出 PDF")
    q.add_argument("job")
    q.add_argument("--chapters", help="只排这几章，逗号分隔，出样张用")
    q.add_argument("--out")
    q.set_defaults(func=cmd_render)

    q = sub.add_parser("prep", help="重采样成 16k 与 22.05k")
    q.add_argument("job")
    q.set_defaults(func=cmd_prep)

    q = sub.add_parser("asr", help="分块转写并补空档")
    q.add_argument("job")
    q.set_defaults(func=cmd_asr)

    q = sub.add_parser("profile", help="素材体检：判断是叙述、跟读还是练习")
    q.add_argument("job")
    q.add_argument("--apply", action="store_true", help="把建议写回 job.json")
    q.set_defaults(func=cmd_profile)

    q = sub.add_parser("dedupe", help="去掉跟读教材里每句念两遍的重复")
    q.add_argument("job")
    q.set_defaults(func=cmd_dedupe)

    q = sub.add_parser("watch", help="实时转写进度条")
    q.add_argument("job")
    q.add_argument("--interval", type=float, default=2.0)
    q.add_argument("--once", action="store_true", help="只打一行就退出")
    q.set_defaults(func=cmd_watch)

    q = sub.add_parser("segment", help="生成断句分段草稿")
    q.add_argument("job")
    q.set_defaults(func=cmd_segment)

    q = sub.add_parser("align", help="把正文对齐到词级时间戳")
    q.add_argument("job")
    q.set_defaults(func=cmd_align)

    q = sub.add_parser("lexicon", help="词典覆盖闸门")
    q.add_argument("job")
    q.set_defaults(func=cmd_lexicon)

    q = sub.add_parser("annotate", help="声学与音系标注")
    q.add_argument("job")
    q.add_argument("--chapters", help="只处理这几章，逗号分隔")
    q.set_defaults(func=cmd_annotate)

    q = sub.add_parser("chapterize", help="自动分章候选 + 复核包")
    q.add_argument("job")
    q.add_argument("--accept", help="接受 decision.json")
    q.add_argument("--no-pitch", action="store_true", help="跳过语调重置打分")
    q.set_defaults(func=cmd_chapterize)

    q = sub.add_parser("meta", help="章节文案请求包 / 接受 meta.json")
    q.add_argument("job")
    q.add_argument("--accept", help="接受 meta.json")
    q.set_defaults(func=cmd_meta)

    q = sub.add_parser("run", help="串行执行全流程")
    q.add_argument("job")
    q.add_argument("--from", dest="from_", help="起始阶段")
    q.add_argument("--to", dest="to", help="结束阶段")
    q.set_defaults(func=cmd_run)

    q = sub.add_parser("init", help="探测音频、生成 job.json")
    q.add_argument("--audio", required=True)
    q.add_argument("--out", required=True)
    q.add_argument("--text", action="store_true", help="已有校订过的正文")
    q.add_argument("--title")
    q.add_argument("--title-en")
    q.add_argument("--language", default="en")
    q.set_defaults(func=cmd_init)
    return p


def main(argv=None) -> int:
    # Windows 控制台默认 GBK，中文输出会乱码
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except JobError as e:
        return _err(str(e))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
