---
name: ipa-study
description: Turn an English audio or video file (plus an optional transcript) into a word-by-word pronunciation study PDF — IPA for every word as actually spoken, measured pitch, prominence, weak forms, linking, unreleased stops, elision, flapping. Use when the user supplies English audio and wants a pronunciation study guide, 发音精读, 逐词音标, interlinear IPA annotations, or a listening-practice booklet.
---

# 发音精读生成线

**产出**：一本 PDF。每个英文词正上方是它在这一段录音里的实际读法；音标上方是
实测音高（H/M/L 与半音差）；下方是弱读时的元音变化；词间弧线是连读；
括号与附加符号是吞音、失爆、浊化。分章本还带全书地图、音高查询表和每章回忆问题。

## 动手前必须知道的一件事

十一条标注里，**音高、重读、时长是声学事实**，必须实测；**弱读、连读、失爆、
吞音、浊化是规则判定**。这条分界线要写进成品首页——读者分不清哪些是测出来的，
整个产品就失去了可信度。详见 [references/annotation.md](references/annotation.md)。

## 输入

| 必需 | 说明 |
|---|---|
| 音频 | mp3/wav/mp4 均可，需要 PATH 上有 `ffmpeg` |
| 文案（可选） | 有校订稿最好；只有原始无标点转写也能做；完全没有就靠 ASR 自己出稿 |

Python 依赖见 `requirements.txt`。字体找不到时运行 `ipa fonts` 会告诉你怎么办。

## 三步上手

```bash
ipa init --audio <音频> --out job.json     # 探测时长，选形态
ipa run job.json                            # 串行跑到第一个闸门
ipa status job.json                         # 看各阶段完成情况
```

`run` 遇到编辑闸门会停下并打印继续命令，**这是设计好的**，不是失败。

转写完先看 `data/profile/report.md`：它会告诉你这段素材是连续讲述、还是每句
念多遍的跟读、还是长留白的练习，并把该改的配置写回 job.json。
先看一眼这个结论，比事后返工便宜得多。详见 [references/material-shape.md](references/material-shape.md)。

转写过程中可以用 `ipa watch job.json` 看实时进度条。

## 阶段

| 阶段 | 做什么 | 闸门 |
|---|---|---|
| `prep` | 转 16k / 22.05k，校验两路等长 | |
| `asr` | 分块转写、补 VAD 吞掉的空档 | |
| `profile` | **素材体检**：判叙述 / 跟读 / 练习，给出配置建议 | |
| `dedupe` | 跟读教材里每句念多遍的，只留第一遍 | |
| `chapterize` | 静音候选 + 打分 + 复核包 | **10** 人工定边界 |
| `segment` | 从时间戳生成断句分段草稿 | **11** 校对粘连词、超长句 |
| `align` | 正文对齐到词级时间戳 | **13** 未匹配率 >2% |
| `lexicon` | 专名词典覆盖闸门 | **12** 未解析词超限 |
| `annotate` | 声学测量 + 音系规则 | |
| `meta` | 章节标题/承接/问题 | **10** 人工写文案 |
| `render` | 排版出 PDF | |
| `qa` | 与金标准比对 | **14** 指标不达标 |

退出码 2 = 配置错，10–14 = 等人做决定。`ipa <阶段> job.json` 可以单步重跑。

## 四个闸门，一个都不能跳

1. **chapterize** — 读 `data/chapterize/review.md`，算法只有停顿和词汇衔接，
   它读不懂内容。切在哪由你定，写 `decision.json` 再 `--accept`。
2. **segment** — 看 `data/segment/review.json`。未拆开的粘词和超长句是断句出错的信号。
3. **lexicon** — 未解析的专名会静默读成 `/ˈʌn/`。补 `data/lexicon/patch.json`，
   否则成品里会有音标错的词，而且你看不出来。
4. **meta** — 标题对了但问题是套话，产品就是空心的。lint 会拦「本章讲述了」。

## 形态自动选择

| 时长 | 形态 | 版面 |
|---|---|---|
| < 12 分钟 | `single` 单篇 | 封面 + 符号表 + 音高表 + 正文 |
| 12–60 分钟 | `sections` 分节 | 加上分节与承接句 |
| > 60 分钟 | `book` 全书 | 再加上全书地图与每章回忆问题 |

## 先出样张

```bash
ipa render job.json --chapters 1 --out sample.pdf
```

**拿到确认之后再渲染全书。** 版式返工比换素材贵得多。

## 参考文档

| 文件 | 什么时候读 |
|---|---|
| [references/material-shape.md](references/material-shape.md) | **转写完先读**：判形态、别踩跟读材料的坑 |
| [references/pipeline.md](references/pipeline.md) | 阶段契约、断点续跑、退出码 |
| [references/job-schema.md](references/job-schema.md) | job.json 全字段 |
| [references/segmentation.md](references/segmentation.md) | 断句、加标点、拆粘词、何时可跳过 DP |
| [references/chapterize.md](references/chapterize.md) | 分章阈值、打分、复核包格式 |
| [references/annotation.md](references/annotation.md) | 音高/重音/弱读规则与**测量边界** |
| [references/rendering.md](references/rendering.md) | 版式参数、字体解析、功能开关 |
| [references/prompts.md](references/prompts.md) | 加标点、定边界、写章节文案的提示词 |
| [references/acceptance.md](references/acceptance.md) | 回归分层与各项指标阈值 |
| [references/troubleshooting.md](references/troubleshooting.md) | 串章、吞词、缺字、内存 |
