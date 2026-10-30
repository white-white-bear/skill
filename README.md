# skill

Claude Code skills 合集。每个 skill 一个子目录，目录名即 skill 名。

## 目录

| Skill | 说明 |
| --- | --- |
| [ipa-study](ipa-study/) | 把英文音频做成逐词行间注的发音精读 PDF：音标、实测音高、强读、弱读、连读、失爆、吞音、浊化 |

## 安装

把某个子目录链接到 Claude Code 的 skills 目录即可。

Windows（在本仓库根目录执行）：

```powershell
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\ipa-study" -Target "$PWD\ipa-study"
```

macOS / Linux：

```bash
ln -s "$PWD/ipa-study" ~/.claude/skills/ipa-study
```
