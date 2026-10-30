# job.json

一份文件驱动全流程。路径一律相对 job.json 所在目录（绝对路径原样使用），
所以整个素材目录可以整体搬走。

## 最小可用

```json
{
  "project": {"title_en": "Steve Jobs", "title_zh": "史蒂夫·乔布斯",
               "slug": "steve-jobs"},
  "audio": {"source": "F:/media/doc.mp3", "duration": 3963.9},
  "text": {"source": "none"},
  "form": {"kind": "auto"},
  "chapters": []
}
```

其余字段会从内置默认值补齐，并**写进文件**，保证以后重跑结果可复现。

## 关键字段

### `text.source`

| 值 | 含义 |
|---|---|
| `none` | 只有音频，正文完全由 ASR 生成（`segment` 会跑） |
| `raw` | 有原始无标点转写，`segment` 会生成草稿 |
| `clean` | 已有校订好的 `chNN_final.txt`（每个空行分段、每行一句），`segment` 直接跳过 |

### `form.kind`

`auto` / `single` / `sections` / `book`。`auto` 按时长决定，阈值见 SKILL.md。
`chapterize --accept` 会把决策结果写回这里。

### `chapters[]`

```json
{"id": 1, "title": "家庭、学校与好奇心", "start": 5.94, "end": 293.3,
 "boundary_source": "chapterize",
 "meta": {"carry": "开场。一个被收养的孩子……", "keys": "收养 · 父亲的工作台 · 惠普",
           "ask": ["父亲的工作台，教给少年 Jobs 的是什么？", "……", "……"]}}
```

- `start/end` 是**唯一**的时间来源。`job validate` 会拦：重叠 >0.5 秒、
  超出音频时长、未排序、`kind=book` 但不足 3 章。
- `boundary_source` 记录来源：`chapterize` / `legacy` / `manual` / `silence`，
  出问题时用来回溯是哪一步定的。

### `lexicon.gate`

```json
{"max_unresolved_ratio": 0.001, "fail_frequency": 2}
```

未解析词占比超过它就让 `lexicon` 退出 12。**不要调高这个值来"通过"**——
它存在的理由见 troubleshooting.md 的「静默读错」。

### `annotate`

| 字段 | 默认 | 含义 |
|---|---|---|
| `accent_threshold` | 0.62 | 突出度打分阈值，超过判为强读 |
| `level_semitones` | 2.2 | H / L 与句内中位的分界（半音） |
| `contour_semitones_per_sec` | 3.5 | 升/降调的斜率阈值 |
| `link_gap_sec` | 0.06 | 词间隔小于它才判连读 |
| `calibration` | `fixed` | 改成 `target_ratio` 时按前几章校准到 `target_accent_ratio` |

这几个值是给一个语速偏慢、音域偏窄的说话人调的。换素材后如果强读比例
明显跑到 10–25% 之外，见 annotation.md 的「校准」。

### `render.features`

`cover` / `map` / `pitch_page` / `legend` / `summary` / `chapter_questions`。
关掉地图但保留分章是合法的（`sections` 形态就这么用）。

## 回灌旧项目

```bash
ipa import-legacy --src <旧项目目录> --out examples/<slug>/job.json
```

会从旧的 `chNN_ann.json` 反推章节边界（不用旧目录的秒数，那些差几十秒）、
把专名词典外提成 `lexicon.json`、生成 `expected_metrics.json`。
章节重叠会被报出来并按"削上一章尾巴"的方式收敛。
