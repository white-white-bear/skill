# -*- coding: utf-8 -*-
"""连读、弱读、失爆、浊化、词尾脱落的美式音系规则，以及数字读法。

这里全部是**规则判定**，不是声学测量。哪些结论来自实测、哪些来自规则，
必须在成品的方法说明里写清楚 —— 这是产品诚实与否的分界线。
"""
from __future__ import annotations

import re

from . import lexicon as C

VOW = C.VOWELS

# ---------------------------------------------------------------- 数字读法

ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
        "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
        "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
        "eighty", "ninety"]
ORD = {"one": "first", "two": "second", "three": "third", "five": "fifth",
       "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}
ORD_TENS = {"twenty": "twentieth", "thirty": "thirtieth", "forty": "fortieth",
            "fifty": "fiftieth", "sixty": "sixtieth", "seventy": "seventieth",
            "eighty": "eightieth", "ninety": "ninetieth"}


def _below100(n):
    if n < 20:
        return ONES[n]
    t, r = divmod(n, 10)
    return TENS[t] + ("-" + ONES[r] if r else "")


def _ordinal(n):
    w = _below100(n)
    if "-" in w:
        a, b = w.split("-")
        return ORD_TENS.get(a, a) if b == "0" else a + "-" + ORD.get(b, b + "th")
    return ORD.get(w, w + "th")


def num_words(tok):
    """24th → twenty-fourth；1955 → nineteen fifty-five；2005 → two thousand five。"""
    md = re.match(r"^(\d{2,4})s$", tok)                 # 年代：1970s → nineteen seventies
    if md:
        n = int(md.group(1))
        if n < 100:
            t = n // 10
            word = TENS[t]
            return (word[:-1] + "ies") if word.endswith("y") else word + "s"
        hi, lo = divmod(n, 100)
        w = _below100(lo)
        return ONES[hi] + " " + (w[:-1] + "ies" if w.endswith("y") else w)
    m = re.match(r"^(\d+)(st|nd|rd|th)?$", tok)
    if not m:
        return tok
    digits, suf = m.group(1), m.group(2)
    n = int(digits)
    if 2000 <= n <= 2099 and not suf:      # 2005 → two thousand five
        r = n - 2000
        return "two thousand" + (" " + _below100(r) if r else "")
    if len(digits) == 4 and 1100 <= n <= 1999:          # 年份读作两个两位数
        hi, lo = divmod(n, 100)
        if lo == 0:
            return ONES[hi] + " hundred"
        lo_w = _below100(lo)
        if lo < 10:
            lo_w = "oh " + ONES[lo]
        return ONES[hi] + " " + lo_w
    if suf:
        return _ordinal(n)
    if n < 100:
        return _below100(n)
    if n < 1000:
        h, r = divmod(n, 100)
        return ONES[h] + " hundred" + (" " + _below100(r) if r else "")
    return tok


def spoken_variants(surface):
    """把一个书写词拆成实际读出来的词序列（数字按读法展开，连字符再拆开）。"""
    out = []
    for part in re.split(r"[-]", surface):
        w = num_words(part)
        for chunk in re.split(r"[\s-]+", w):
            if chunk:
                out.append(chunk.strip("'"))
    return [p for p in out if p]


# ---------------------------------------------------------------- 弱读

# 这些词几乎只以弱读出现，不作强读分析
CLITIC = {"a", "an", "the", "of", "to", "and", "in", "on", "at", "for", "from",
          "with", "as", "but", "than", "that", "was", "were", "is", "are", "am",
          "be", "has", "have", "had", "do", "does", "did", "can", "could",
          "would", "should", "will", "must", "some", "such", "just", "not",
          "his", "him", "her", "them", "us", "me", "my", "your", "our", "you",
          "he", "she", "we", "they", "there", "into"}


# ---------------------------------------------------------------- 连读

LINK_GLIDE = {"iː": "j", "ɪ": "j", "eɪ": "j", "aɪ": "j", "ɔɪ": "j",
              "uː": "w", "ʊ": "w", "oʊ": "w", "aʊ": "w"}


def link_type(last_phone, next_phone):
    """只返回真正的连读：辅音接元音、元音接元音、同音辅音合并。"""
    if last_phone is None or next_phone is None:
        return None
    lv = C.strip_stress(last_phone) in VOW
    nv = C.strip_stress(next_phone) in VOW
    if lv and nv:
        return "V-V"
    if (not lv) and nv:
        return "C-V"
    if C.strip_stress(last_phone) == C.strip_stress(next_phone) and not lv:
        return "C-C"          # 同音辅音合并，只保留一次除阻
    return None


# ---------------------------------------------------------------- 失爆 / 浊化 / 脱落

STOPS = {"P", "T", "K", "B", "D", "G"}


def is_vowel(p):
    return C.strip_stress(p) in VOW


def is_sonorant(p):
    """能承接闪音的前导音。/n/ /m/ 后面更常见的是直接删掉 /t/，不按浊化处理。"""
    return C.strip_stress(p) in ("R", "L")


def final_changes(phones, nxt_phones, sentence_final, next_starts_vowel):
    """返回 (unreleased, elided, flapped) 三组音素**下标**。

    必须用下标：一个词里可能有两个 /t/，按字符串匹配会把它们一起标掉。
    """
    unreleased, elided, flapped = set(), set(), set()
    if not phones:
        return unreleased, elided, flapped
    n = len(phones)

    # 1) 词尾塞音：后接辅音或位于停顿前 → 只有成阻没有除阻
    if C.strip_stress(phones[-1]) in STOPS:
        if (not next_starts_vowel) or sentence_final:
            unreleased.add(n - 1)
            # 词尾 /t/ /d/ 后接辅音时常整个消失（省音），不是"不除阻"
            if C.strip_stress(phones[-1]) in ("T", "D") and nxt_phones \
                    and not is_vowel(nxt_phones[0]):
                elided.add(n - 1)
                unreleased.discard(n - 1)

    # 2) 词内 /t d/ 在浊音后、非重读元音前 → 闪音（与整词是否重读无关，
    #    只看后一元音是否非重读：ˈlɪɾl̩、ˈstɑːɾɪd 都是这样）
    for i in range(1, n - 1):
        if C.strip_stress(phones[i]) not in ("T", "D"):
            continue
        if not (is_vowel(phones[i - 1]) or is_sonorant(phones[i - 1])):
            continue
        if not is_vowel(phones[i + 1]):
            continue
        if phones[i + 1][-1:] == "1":        # 后一元音重读则不浊化
            continue
        flapped.add(i)

    # 3) 跨词浊化：...Vt || 元音开头的下一个词（get it → ɡɛɾɪt）
    if next_starts_vowel and n >= 2:
        if C.strip_stress(phones[-1]) in ("T", "D") and (
                is_vowel(phones[-2]) or is_sonorant(phones[-2])):
            flapped.add(n - 1)
            unreleased.discard(n - 1)
            elided.discard(n - 1)

    return unreleased, elided, flapped


FLAP = "ɾ"


def render_word(phones, unreleased=(), elided=(), flapped=(), show_stress=True,
                breaks=(), sylls=None):
    """把音素串渲染成带标记的 IPA：闪音 ɾ、不除阻 ̚、脱落 (t)。

    sylls 由调用方传入时直接使用，避免对拼好的音素串重新切分导致
    数字读法（nineteen sixty-one）的音节边界对不上。
    breaks 是要断开成独立词的音节下标。
    """
    sylls = sylls if sylls is not None else C.syllabify(phones)
    # 同一个读出单位里只留一个主重音：取最后一个标了 1 的音节
    group, groups = 0, {}
    for k, s in enumerate(sylls):
        if k in breaks:
            group += 1
        groups.setdefault(group, []).append(k)
    mark_of = {}
    for g, ks in groups.items():
        prim = [k for k in ks if sylls[k]["stress"] == 1]
        if prim:
            mark_of[prim[-1]] = "ˈ"
            if len(prim) > 1:
                mark_of[prim[-2]] = "ˌ"

    parts = []
    gi = 0
    for k, s in enumerate(sylls):
        mark = mark_of.get(k, "") if show_stress else ""
        if k in breaks:
            mark = " " + mark
        seg = []
        for p in s["phones"]:
            if gi in flapped:
                seg.append(FLAP)
            elif gi in elided:
                seg.append("(" + C.phone_ipa(p) + ")")
            elif gi in unreleased:
                seg.append(C.phone_ipa(p) + "̚")
            else:
                seg.append(C.phone_ipa(p))
            gi += 1
        parts.append(mark + "".join(seg))
    return "".join(parts)
