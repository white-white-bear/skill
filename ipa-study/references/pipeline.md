# 阶段契约

整条线靠 `data/` 下的文件传递状态，脚本之间不共享进程。每个阶段都可以单独重跑。

## 文件表

| 阶段 | 输入 | 输出 |
|---|---|---|
| `prep` | `audio.source` | `audio/full_16k.wav`、`audio/full_22k.wav` |
| `asr` | `full_16k.wav` | `data/asr/chunk_NNN.jsonl`（首行是头部）、`data/asr/plan.json`、`data/words.jsonl` |
| `profile` | `words.jsonl` | `data/profile/report.md`；`--apply` 写回 job |
| `dedupe` | `words.jsonl` | `data/words.jsonl`（去重后）、`data/words_raw.jsonl`（原始）、`data/dedupe/report.json` |
| `chapterize` | `words.jsonl` | `data/chapterize/{candidates.json,review.md}`；`--accept` 写回 job |
| `segment` | `words.jsonl` + 章边界 | `data/chNN_final.txt`、`data/segment/review.json` |
| `align` | `chNN_final.txt` + `words.jsonl` | `data/chNN_units.json`、`data/align/report.json` |
| `lexicon` | 全部 `chNN_final.txt` | `data/lexicon/{report.json,patch.json}` |
| `annotate` | `chNN_units.json` + `full_22k.wav` | `data/chNN_ann.json`、`data/acoustics.json` |
| `meta` | `chNN_ann.json` | `data/meta/request.md`；`--accept` 写回 job |
| `render` | `chNN_ann.json` + job 文案 | `out/<slug>.pdf` |
| `qa` | `chNN_ann.json` + PDF | 报告 + 退出码 |

## 断点续跑

每阶段/每章写 `data/state/<stage>[.NN].json`，记 `config_hash` 与各输出的哈希。

跳过条件只有一条：**状态文件在 + 输出在 + 哈希对得上 + 配置片段没变**。
没有"大概没变"的中间态。改章节标题只会让 `render` 失效，不会让 `asr` 重跑。

- `--force` 强制重跑
- `ipa status job.json` 打印完成矩阵

## 退出码

| 码 | 含义 | 该做什么 |
|---|---|---|
| 0 | 成功 | 继续 |
| 2 | 配置错误 | 修 job.json |
| 10 | 等人定分章 / 写章节文案 | 读 review.md 或 request.md，写 decision/meta 后 `--accept` |
| 11 | 等人校对断句 | 处理 `segment/review.json` |
| 12 | 词典闸门 | 补 `lexicon/patch.json` |
| 13 | 对齐闸门（未匹配 >2%） | 检查文案与音频是不是同一个素材 |
| 14 | 验收不达标 | 看 `qa` 报告 |

`run` 默认遇闸门即停。设计如此：这四个闸门跳过任意一个，产出都会"看起来对但空洞"。

## 时间轴的唯一来源

旧版把章节边界抄在六个地方且互不相等（`build_all.SPAN`、`book_meta.span` 字符串、
`asr_rest.OFFSET=296`、`<300` 阈值、`SPAN[1]=308`、`split_chapters` 的正则），
换素材必出串章。现在只有一个来源：`job.chapters[].start/end`。
显示用的 "00:00–04:53" 由 `format_span()` 现算，不存储。

## 音频两路必须等长

`prep` 生成 16k（给 ASR）和 22.05k（给声学分析），`check_pair()` 校验时长差
≤0.1 秒。只重采样，**绝不裁剪**——任何裁剪都会让两路时间轴错开，
后面所有音高数字都会对应到错误的词上。
