"""Small, reversible voice-only text normalization. Never mutates DSH replies."""
from __future__ import annotations
import re

_PROPER_NAMES = (
    (re.compile(r"(?<![A-Za-z])Wendy(?![A-Za-z])", re.IGNORECASE), "温蒂"),
    (re.compile(r"(?<![A-Za-z])Qwen(?![A-Za-z])", re.IGNORECASE), "千问"),
)

def prepare_spoken_text(reply: str) -> str:
    if not isinstance(reply, str) or not reply.strip():
        raise ValueError("empty_spoken_text")
    # Full response remains in the Mac app; this is pronunciation only.
    # Markdown tables/code are layout, not ordinary spoken Chinese. When a
    # user explicitly wants full reading, retain prose while referring to
    # the visual table (all rows remain available in Mac history).
    reply=re.sub(r'(?ms)^\s*```.*?^\s*```\s*$', '代码内容请在Mac查看。',reply)
    lines=[];had_table=False
    for line in reply.splitlines():
        t=line.strip()
        # R555: section headings are page layout, not oral script. A numbered
        # heading of the form "五、它替代不了...的原因" can otherwise be
        # selected as an isolated "fact" while the underlying explanation is
        # omitted. Retain only its original factual caveat, without the
        # table-of-contents number or the misleading dangling "的原因".
        heading=re.fullmatch(
            r'(?:#{1,6}\s*)?(?:[一二三四五六七八九十]{1,3}[、.．]\s*)([^。！？\n]{1,45})',
            t)
        if heading:
            claim=heading[1].strip()
            if (claim.endswith('的原因') and any(w in claim for w in
                    ('替代不了','不能代替','不能替代','无法代替','无法替代','不等于'))):
                t='要注意，'+claim[:-3].strip(' ，：:')+'。'
            elif (len(claim)<=24 and (claim in
                    ('优势','缺点','原因','局限','限制','结论','总结','背景','前提','意义')
                    or claim.endswith(('的原理','的原因','的作用','的优势','的局限',
                                        '的限制','的区别')))):
                # The actual following prose holds the facts; do not choose a
                # section label as a standalone 1-minute spoken sentence.
                continue
            else:
                t=claim
            line=t
        if t.count('|')>=2:
            if not had_table:lines.append('表格数据请在Mac查看。')
            had_table=True
            continue
        if re.fullmatch(r'[\s|:—\-+]+',t):continue
        lines.append(line)
    reply='\n'.join(lines)
    text = re.sub(r"\[([^\]]{1,120})\]\(https?://[^\s)]{1,800}\)", r"\1", reply)
    text = re.sub(r"https?://[^\s]+", "链接请在Mac查看", text)
    text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}|[-*+]\s+|\d+[.)]\s+)", "", text)
    text = re.sub(r"[*`_~]", "", text)
    for pattern, pronunciation in _PROPER_NAMES:
        text = pattern.sub(pronunciation, text)
    # Keep the original full DSH answer in Mac; only optimize spoken delivery.
    # A Markdown list break isn't an audible paragraph. Preserve content while
    # replacing layout newlines with ordinary Chinese spoken clause pauses.
    text = re.sub(r"(?m)^\s*>\s*", "", text)
    text = re.sub(r"\s*\n+\s*", "；", text)
    # R555: short section titles also leak through already condensed oral
    # scripts as inline phrases ("...。五、它替代不了X的原因；...").
    # Converting a true negation/caveat into a natural sentence preserves
    # the original claim, without reciting the page's section number.
    def natural_caveat(m):
        return '要注意，'+m.group(1)+'。'
    text=re.sub(
        r"(?<=[。！？；])\s*[一二三四五六七八九十]{1,3}[、.．]\s*"
        r"([^。！？；\n]{0,36}?(?:替代不了|不能替代|不能代替|无法替代|无法代替)"
        r"[^。！？；\n]{0,20}?)的原因(?=[。；\n]|$)",
        natural_caveat,text)
    text = re.sub(r"([。！？；，])\1+", r"\1", text)
    text = re.sub(r"([。！？])；", r"\1", text)
    # R680: date ISO-8601 token 2026-09-29 is not a numeric range.
    # Require BOTH numbers to end at token boundaries so regex cannot
    # backtrack into a partial date, while 30-40g still reads as a range.
    text = re.sub(r"(?<![0-9-])([0-9]+)\s*[-~～—]\s*([0-9]+)(?![0-9-])",
                  r"\1到\2", text)
    text = text.replace("元/斤","元一斤").replace("元／斤","元一斤")
    return text.strip(" ；")
