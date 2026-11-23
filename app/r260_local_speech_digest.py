"""R265 deterministic, content-bearing voice fallback for verified Markdown.

No second model, network call or mutation of the verified DSH answer. Strip
layout/code/links, then read multiple complete factual clauses instead of a
60-character title-like prefix. Tables are only previewed, never raw-read.
"""
from __future__ import annotations
import re

MAX_SPOKEN = 240
NOTICE = '更多细节请看Mac。'
FALLBACK = '详细内容请看Mac。'


def _clean(line: str) -> str:
    line = re.sub(r'^(?:>\s*)+', '', line)
    line = re.sub(r'^[-*+]\s+', '', line)
    line = re.sub(r'^\d{1,3}[.)]\s+', '', line)
    line = re.sub(r'\[(.{1,80}?)\]\(https?://[^\s)]*\)', r'\1', line)
    line = re.sub(r'https?://\S+', '', line)
    line = re.sub(r'[`*_~]', '', line)
    return re.sub(r'\s+', ' ', line).strip(' ；')


def _clauses(text: str):
    for clause in re.split(r'(?<=[。！？；])', text):
        clause = clause.strip(' ；')
        if clause and re.search(r'[\u4e00-\u9fff]', clause):
            yield clause if clause.endswith(('。', '！', '？', '；')) else clause + '。'


def local_spoken_digest(markdown: str, *, limit: int = MAX_SPOKEN) -> str:
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError('empty_verified_reply')
    if not 35 <= limit <= 400:
        raise ValueError('invalid_spoken_limit')
    # R266: steps 4-7 must survive the spoken version; 240 chars is an
    # unsuitable hard cap for a real 4+ stage procedure.
    from app.r266_structured_voice import structured_spoken_digest
    structured = structured_spoken_digest(markdown)
    if structured is not None:
        return structured
    source = re.sub(r'(?ms)^\s*```.*?^\s*```\s*$', ' ', markdown)
    prose, rows, headers = [], [], []
    in_table = False
    for raw in source.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.count('|') >= 2:
            in_table = True
            cells = [ _clean(cell) for cell in line.strip('|').split('|') ]
            if not cells or all(not cell or re.fullmatch(r'[-:+\s]+', cell) for cell in cells):
                continue
            # Only representative data rows. Header cells alone convey no facts.
            if not headers:
                headers = cells
            elif len(rows) < 3:
                # Keep the column association in the spoken row.
                row = '，'.join(f'{head}{value}' if head and value and
                               len(head) <= 7 and head not in value
                               else value for head, value in zip(headers, cells) if value)
                if row and re.search(r'[\u4e00-\u9fff]', row):
                    rows.append(row + '。')
            continue
        if re.fullmatch(r'[\s|:\-+]+', line):
            continue
        # Bare Markdown titles have historically consumed the entire 60-char
        # budget. Treat them as structure, not the factual first sentence.
        if re.match(r'^#{1,6}\s+', line):
            continue
        cleaned = _clean(line)
        if len(cleaned) < 4 or not re.search(r'[\u4e00-\u9fff]', cleaned):
            continue
        if re.fullmatch(r'(?:结果|表格|内容|数据)(?:如下|见下表)[：:]?', cleaned):
            continue
        prose.extend(_clauses(cleaned))
    notice = NOTICE if in_table else FALLBACK
    budget = limit - len(notice)
    chosen = []
    remaining = budget
    # Factual prose first. A limited number of table rows will follow, so a
    # table-first Markdown answer does not become a spoken column-heading list.
    candidates = prose[:18] + rows
    for part in candidates:
        if part in chosen:
            continue
        if len(part) > remaining:
            continue  # Never stop a sentence in the middle.
        chosen.append(part)
        remaining -= len(part)
        if remaining < 16:
            break
    if not chosen:
        # Exceptional one-paragraph text without sentence punctuation:
        # retain a bounded factual excerpt rather than just a title.
        first = next(iter(prose), '这次回答含较长内容。')
        chosen = [first[:max(1, budget - 1)].rstrip('，、； ') + '。']
    spoken = ''.join(chosen).strip()
    return spoken[:budget] + notice
