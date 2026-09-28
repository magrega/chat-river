#!/usr/bin/env python3
"""Chat River · шаг 2: личный Ngram Viewer → out/ngram-viewer.html."""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'out'
MIN_COUNT = 10
P_SPLIT = None  # эпохи для «рождения/смерти слов» подберутся автоматически (половины корпуса)
URL_RE = re.compile(r'(?:https?://|www\.)\S+', re.IGNORECASE)
TOKEN_RE = re.compile(r'[а-яёa-z0-9]+')
EXAMPLES = ['работ*', 'спасибо, извини', 'люблю', 'думаю, чувствую']

rows = duckdb.connect().execute(f"""
  SELECT strftime(ts, '%Y-%m') m, text FROM '{ROOT}/data/messages.parquet'
  WHERE is_mine AND NOT is_forwarded AND n_tokens > 0 ORDER BY 1""").fetchall()
if not rows:
    raise SystemExit('Нет данных: сначала python scripts/01_prepare.py <путь к result.json>')

month_tok = defaultdict(Counter)
totals = Counter()
for m, text in rows:
    toks = [t for t in TOKEN_RE.findall(URL_RE.sub(' ', text).lower().replace('ё', 'е'))
            if len(t) >= 2]
    if toks:
        totals[m] += len(toks)
        month_tok[m].update(toks)

months = sorted(totals)
mindex = {mm: i for i, mm in enumerate(months)}
grand = Counter()
for mm in months:
    grand.update(month_tok[mm])
vocab = {}
for w, c in grand.items():
    if c >= MIN_COUNT:
        vocab[w] = [[mindex[mm], month_tok[mm][w]] for mm in months if month_tok[mm].get(w)]

half = months[len(months) // 2]
p1 = [mm for mm in months if mm < half]
p2 = [mm for mm in months if mm >= half]
n1 = sum(totals[mm] for mm in p1) or 1
n2 = sum(totals[mm] for mm in p2) or 1
c1, c2 = Counter(), Counter()
for mm in p1: c1.update(month_tok[mm])
for mm in p2: c2.update(month_tok[mm])
years = sorted({mm[:4] for mm in months})
ytot = Counter(); yc = defaultdict(Counter)
for mm in months:
    ytot[mm[:4]] += totals[mm]; yc[mm[:4]].update(month_tok[mm])

def spark(w):
    return [round(yc[y].get(w, 0) * 10000 / ytot[y], 3) if ytot[y] else 0 for y in years]

scored = sorted(((( (c2.get(w, 0) + .5) * 10000 / n2) / ((c1.get(w, 0) + .5) * 10000 / n1), w)
                 for w, tot in grand.items() if tot >= max(30, MIN_COUNT * 3) and not w.isdigit()),
                reverse=True)
rows_ = lambda items: [{'w': w, 'ratio': round(r if r >= 1 else 1 / r, 2), 'spark': spark(w)}
                       for r, w in items]
payload = {'months': months, 'totals': [totals[mm] for mm in months], 'vocab': vocab,
           'rising': rows_(scored[:25]), 'dying': rows_(scored[-25:][::-1]),
           'meta': {'messages': len(rows), 'tokens': sum(totals.values()),
                    'minCount': MIN_COUNT, 'p1': f'{months[0]} — {p1[-1] if p1 else months[0]}',
                    'p2': f'{half} — {months[-1]}', 'buffer': '—', 'examples': EXAMPLES}}
blob = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
tpl = (ROOT / 'templates' / 'ngram_template.html').read_text(encoding='utf-8')
OUT.mkdir(exist_ok=True)
(OUT / 'ngram-viewer.html').write_text(tpl.replace('__DATA__', blob), encoding='utf-8')
print(f'out/ngram-viewer.html: {len(vocab)} токенов в словаре, {len(months)} месяцев')
