# -*- coding: utf-8 -*-
"""词典查询与 ARPAbet → IPA 转换。

专用名词（人名、地名、产品名）不放在这里：每部素材自己的词表由
job.lexicon.project 指定，运行时由 configure() 注入。旧项目把这些
写死在 common.py 里，换一部片子就会把 120 个专名读成 /ˈʌn/。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import cmudict

DICT = cmudict.dict()

VOWELS = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY",
          "IH", "IY", "OW", "OY", "UH", "UW"}

ARPABET_IPA = {
    "AA": "ɑː", "AE": "æ", "AH": "ʌ", "AO": "ɔː", "AW": "aʊ", "AY": "aɪ",
    "EH": "ɛ", "ER": "ɜːr", "EY": "eɪ", "IH": "ɪ", "IY": "iː", "OW": "oʊ",
    "OY": "ɔɪ", "UH": "ʊ", "UW": "uː",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ", "HH": "h",
    "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ", "P": "p",
    "R": "r", "S": "s", "SH": "ʃ", "T": "t", "TH": "θ", "V": "v", "W": "w",
    "Y": "j", "Z": "z", "ZH": "ʒ",
}

LETTER = {
    "A": "EY1", "B": "B IY1", "C": "S IY1", "D": "D IY1", "E": "IY1", "F": "EH1 F",
    "G": "JH IY1", "H": "EY1 CH", "I": "AY1", "J": "JH EY1", "K": "K EY1",
    "L": "EH1 L", "M": "EH1 M", "N": "EH1 N", "O": "OW1", "P": "P IY1",
    "Q": "K Y UW1", "R": "AA1 R", "S": "EH1 S", "T": "T IY1", "U": "Y UW1",
    "V": "V IY1", "W": "D AH1 B AH0 L Y UW0", "X": "EH1 K S", "Y": "W AY1",
    "Z": "Z IY1",
}

ROMAN = {"II": 2, "III": 3, "IV": 4, "VI": 6, "VII": 7, "VIII": 8, "IX": 9,
         "XI": 11, "XII": 12, "XVIII": 18}

# 由 configure() 注入的素材专属条目
_MANUAL: dict = {}
_ACRONYM: dict = {}
_PRODUCTS: dict = {}
UNRESOLVED: dict = {}          # norm -> 出现次数，供 lexicon 闸门用


def configure(project: dict | None = None, manual: dict | None = None) -> None:
    """project 形如 {"manual": {...}, "acronyms": {...}, "products": {...}}。"""
    _MANUAL.clear(); _ACRONYM.clear(); _PRODUCTS.clear()
    for src in (project or {}, {"manual": manual or {}}):
        _MANUAL.update({k.lower(): v for k, v in (src.get("manual") or {}).items()})
        _ACRONYM.update({k.upper(): v for k, v in (src.get("acronyms") or {}).items()})
        _PRODUCTS.update({k.lower(): v for k, v in (src.get("products") or {}).items()})


def load_project_lexicon(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def lookup(word: str, pos_hint: int = 0):
    """返回 [ARPAbet 带重音数字的音素] 或 None。"""
    raw = word.strip()
    w = re.sub(r"[^a-z0-9]", "", raw.lower())
    if w in _MANUAL:
        return _MANUAL[w].split()
    if raw.upper() in _ACRONYM:
        return _ACRONYM[raw.upper()].split()
    if raw.upper() in ROMAN:
        from .phonology import num_words
        return lookup(num_words(str(ROMAN[raw.upper()])))
    if w in _PRODUCTS:
        return _PRODUCTS[w].split()
    for key in (raw.lower(), w):           # didn't 这类带撇号的词要先试原形
        if key in DICT:
            return DICT[key][min(pos_hint, len(DICT[key]) - 1)]
    # 所有格：Wozniak's → 查 wozniak
    if w.endswith("s") and (raw.lower().endswith("'s") or raw.lower().endswith("’s")):
        got = lookup(raw[:-2], pos_hint)
        if got:
            if strip_stress(got[-1]) in ("S", "Z", "SH", "ZH", "CH", "JH"):
                return got + ["IH0", "Z"]
            return got + ["Z"]
    # 缩写复数：CEOs → C E O + Z
    if raw.endswith("s") and len(raw) > 2 and raw[:-1].isupper() \
            and raw[:-1].isalpha() and all(ch in LETTER for ch in raw[:-1]):
        base_ph = lookup(raw[:-1], pos_hint)
        if base_ph:
            return base_ph + ["Z"]
    # 首字母缩写：全大写、2–5 个字母
    if raw.isupper() and 2 <= len(raw) <= 5 and raw.isalpha() and \
            all(ch in LETTER for ch in raw):
        out = []
        for k, ch in enumerate(raw):
            phones = LETTER[ch].split()
            if k < len(raw) - 1:              # 除最后一个字母外都压成次重音
                phones = [re.sub(r"1$", "2", p) if p[-1:].isdigit() else p
                          for p in phones]
            out += phones
        return out
    # 复合词：MacWrite / Cyberdog 之类，试拆两半
    if len(w) > 5:
        for i in range(3, len(w) - 2):
            a, b = w[:i], w[i:]
            pa, pb = _MANUAL.get(a) or DICT.get(a), _MANUAL.get(b) or DICT.get(b)
            if pa and pb:
                sa = pa.split() if isinstance(pa, str) else pa[0]
                sb = pb.split() if isinstance(pb, str) else pb[0]
                sa = [re.sub(r"1$", "2", p) if p[-1:].isdigit() else p for p in sa]
                return sa + sb
    UNRESOLVED[w] = UNRESOLVED.get(w, 0) + 1
    return None


def strip_stress(p: str) -> str:
    return re.sub(r"[012]$", "", p)


def phone_ipa(p: str) -> str:
    """单个 ARPAbet 音素转 IPA；AH0/ER0 这类弱读元音单独处理。"""
    base = strip_stress(p)
    stressed = p[-1:] == "1"
    if base == "AH":
        return "ʌ" if stressed else "ə"
    if base == "ER":
        return "ɜːr" if stressed else "ɚ"
    return ARPABET_IPA.get(base, base.lower())


def to_ipa(phones, stress_marks: bool = True):
    """把 ARPAbet 串转成 IPA，按音节插入 ˈ ˌ。返回 (ipa, sylls)。"""
    sylls = syllabify(phones)
    for s in sylls:
        s["ipa"] = [phone_ipa(p) for p in s["phones"]]
    prim = [k for k, s in enumerate(sylls) if s["stress"] == 1]
    sec = [k for k, s in enumerate(sylls) if s["stress"] == 2]
    keep_sec = None
    for k in sec:
        if all(abs(k - p) > 1 for p in prim):
            keep_sec = k
            break
    out = []
    for k, s in enumerate(sylls):
        mark = ""
        if stress_marks and s["stress"] == 1:
            mark = "ˈ"
        elif stress_marks and k == keep_sec:
            mark = "ˌ"
        out.append(mark + "".join(s["ipa"]))
    return "".join(out), sylls


ONSETS = {"pr", "tr", "kr", "br", "dr", "gr", "fr", "thr", "shr",
          "pl", "kl", "bl", "gl", "fl", "sl",
          "sp", "st", "sk", "sm", "sn", "sw", "tw", "dw", "kw",
          "py", "by", "ty", "dy", "ky", "gy", "my", "ny", "fy", "vy", "hy",
          "spr", "str", "skr", "spl", "skw", "sf"}


def is_onset(cluster) -> bool:
    """这一串辅音能否整体做后一首节的起首（NG 不能起首，其余单辅音都可以）。"""
    key = "".join(strip_stress(c).lower() for c in cluster)
    if len(cluster) == 1:
        return key != "ng"
    return key in ONSETS


def syllabify(phones) -> list:
    """按元音切音节，辅音按最大起首原则分配。"""
    nuclei = [i for i, p in enumerate(phones) if strip_stress(p) in VOWELS]
    if not nuclei:
        return [dict(phones=phones,
                     ipa=[ARPABET_IPA.get(strip_stress(p), strip_stress(p).lower())
                          for p in phones], stress=0)]
    bounds = []
    for k, nuc in enumerate(nuclei):
        if k == 0:
            start = 0
        else:
            prev = nuclei[k - 1]
            cluster = phones[prev + 1:nuc]
            take = 0
            for n in range(len(cluster), 0, -1):
                if is_onset(cluster[len(cluster) - n:]):
                    take = n
                    break
            start = nuc - take
        bounds.append(start)
    bounds.append(len(phones))
    sylls = []
    for k in range(len(nuclei)):
        seg = phones[bounds[k]:bounds[k + 1]]
        stress = 0
        for p in seg:
            if strip_stress(p) in VOWELS and p[-1:].isdigit():
                stress = int(p[-1])
                break
        sylls.append(dict(phones=seg, ipa=[phone_ipa(p) for p in seg], stress=stress))
    return sylls


def unresolved_report(min_freq: int = 1) -> list:
    """未解析词按频次降序，供闸门展示与补录。"""
    return sorted(((w, n) for w, n in UNRESOLVED.items() if n >= min_freq),
                  key=lambda x: (-x[1], x[0]))
