#!/usr/bin/env python3
"""Chat River · шаг 4: языковой двойник Big5 → out/big5.html.

Читает баллы теста из my_big5.md (шаблон: templates/big5-results-template.md);
без него строит только корпусную половину. Всё локально; вердиктов не выносит —
показывает числа и объясняет, как их читать.
"""
import re
from datetime import date
from pathlib import Path

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'out'
con = duckdb.connect()
MSG = f"'{ROOT}/data/messages.parquet'"
CHT = f"'{ROOT}/data/chats.parquet'"

# ---------- баллы теста ----------
DOM = {'нейротизм': 'N', 'neuroticism': 'N', 'экстраверсия': 'E', 'extraversion': 'E',
       'открытость': 'O', 'openness': 'O', 'доброжелательность': 'A', 'agreeableness': 'A',
       'добросовестность': 'C', 'conscientiousness': 'C'}
scores = {}
f = ROOT / 'my_big5.md'
if f.exists():
    for line in f.read_text(encoding='utf-8').splitlines():
        m = re.match(r'\s*[-*]?\s*([А-Яа-яA-Za-z]+)\s*[:—-]\s*(\d+)', line)
        if m and m.group(1).lower() in DOM:
            scores[DOM[m.group(1).lower()]] = int(m.group(2))
    print(f'баллы теста: {scores or "не распознаны — проверь формат my_big5.md"}')
else:
    print('my_big5.md не найден — строю только корпусную половину '
          '(шаблон: templates/big5-results-template.md)')

# ---------- корпусные индикаторы ----------
pats = {
 'polite': r'\b(спасибо|благодар\w*|пожалуйста|извин\w*|прости\w*|сорр?и|сорян)\b',
 'anxiety': r'\b(трево\w+|боюсь|страшно|страх\w*|паник\w*|пережива\w+|нервнича\w+)\b',
 'anger': r'\b(бесит\w*|злюсь|злит\w*|ненави\w+|раздража\w+|достал\w*)\b',
 'sad': r'\b(грустн?\w*|тоск\w+|печал\w+|депрес\w+|устал\w*|выгор\w+|одинок\w+)\b',
 'positive': r'\b(рад\w{0,3}|круто|клево|классно|здорово|отлично|прекрасн\w+|люблю|обожаю|счастлив\w*|кайф\w*)\b',
 'laugh': r'(ахах+|хах+а|хех+|лол|ржу|ору)',
 'i_words': r'\b(я|меня|мне|мной|мною|мой|моя|мое|мои)\b',
 'we_words': r'\b(мы|нас|нам|нами|наш|наша|наше|наши)\b',
}
comp = {k: re.compile(v, re.I) for k, v in pats.items()}
TOK = re.compile(r'[а-яёa-z0-9]+')

inner_ids = [r[0] for r in con.execute(f"""
  SELECT chat_id FROM {MSG} m JOIN {CHT} c USING (chat_id)
  WHERE c.type='personal_chat' GROUP BY 1 ORDER BY count(*) DESC LIMIT 10""").fetchall()]
ph = ','.join(str(i) for i in inner_ids) or '0'

def lex_profile(where):
    rows = con.execute(f"""SELECT text FROM {MSG} m
      WHERE is_mine AND NOT is_forwarded AND n_tokens>0 AND {where}""").fetchall()
    ntok = sum(len(TOK.findall(t[0].lower())) for t in rows) or 1
    out = {'n_msgs': len(rows)}
    for k, rgx in comp.items():
        out[k] = round(sum(len(rgx.findall(t[0].lower().replace('ё', 'е'))) for t in rows)
                       * 10000 / ntok, 1)
    return out

full = lex_profile('TRUE')
inner = lex_profile(f'chat_id IN ({ph})')
outer = lex_profile(f'chat_id NOT IN ({ph})')

days = con.execute(f"SELECT date_diff('day', min(ts), max(ts))+1 FROM {MSG}").fetchone()[0] or 1
msgs_day = con.execute(f"SELECT round(count(*)/{days}.0,1) FROM {MSG} WHERE is_mine").fetchone()[0]
dialogs_mo = con.execute(f"""SELECT round(avg(n),1) FROM (
  SELECT strftime(ts,'%Y-%m') mm, count(DISTINCT chat_id) n FROM {MSG} m
  JOIN {CHT} c USING (chat_id) WHERE c.type='personal_chat' GROUP BY 1)""").fetchone()[0]
night = con.execute(f"SELECT round(avg((hour(ts) BETWEEN 0 AND 5)::int)*100,1) FROM {MSG} WHERE is_mine").fetchone()[0]
init = con.execute(f"""
  WITH o AS (SELECT m.chat_id, m.ts, m.is_mine,
      CASE WHEN lag(m.ts) OVER w IS NULL OR epoch(m.ts)-epoch(lag(m.ts) OVER w)>3600
           THEN 1 ELSE 0 END ns
    FROM {MSG} m JOIN {CHT} c USING (chat_id) WHERE c.type='personal_chat'
    WINDOW w AS (PARTITION BY m.chat_id ORDER BY m.ts, m.msg_id))
  SELECT round(avg(is_mine::int)*100) FROM o WHERE ns=1""").fetchone()[0]
i_we = round(full['i_words'] / max(full['we_words'], 0.1), 1)
posneg = round(full['positive'] / max(full['anxiety'] + full['anger'] + full['sad'], 0.1), 1)

def card(v, l, n=''):
    return (f'<div class="ind"><div class="v">{v}</div><div class="l">{l}</div>'
            + (f'<div class="n">{n}</div>' if n else '') + '</div>')

def dom_row(code, title, test_note, inds, reading):
    sc = scores.get(code)
    test = f'твой балл: <b>{sc}</b>' if sc is not None else 'балл не указан (my_big5.md)'
    return (f'<h2>{title}</h2><div class="test">{test} · {test_note}</div>'
            f'<div class="inds">{inds}</div><div class="read">{reading}</div>')

html = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Языковой двойник Big5</title><style>
body{{margin:0;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;background:#f9f9f7;color:#0b0b0b}}
.wrap{{max-width:900px;margin:0 auto;padding:28px 16px 56px}}
h1{{font-size:25px;margin:0 0 4px}} h2{{font-size:19px;margin:28px 0 2px}}
.sub{{color:#52514e;font-size:13px;margin:0 0 10px;max-width:78ch}}
.test{{font-size:13px;color:#52514e;background:#fcfcfb;border:1px solid rgba(11,11,11,.1);border-radius:10px;padding:9px 13px;margin:6px 0}}
.inds{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;margin:8px 0}}
.ind{{background:#fcfcfb;border:1px solid rgba(11,11,11,.1);border-radius:10px;padding:10px 12px}}
.ind .v{{font-size:20px;font-weight:600}} .ind .l{{font-size:12px;color:#52514e;margin-top:2px}}
.ind .n{{font-size:11px;color:#898781;margin-top:3px}}
.read{{font-size:13.5px;line-height:1.55;color:#333;max-width:80ch;border-left:3px solid #c3c2b7;padding:2px 0 2px 12px;margin:6px 0}}
.foot{{color:#898781;font-size:12px;line-height:1.6;margin-top:26px;max-width:82ch}}
</style></head><body><div class="wrap">
<h1>Языковой двойник Big5</h1>
<p class="sub">Твой личностный тест против твоего реального языка: {full['n_msgs']:,} твоих
сообщений. Никаких вердиктов — только два измерения одного человека и подсказки, как их
сравнивать. Собрано {date.today().isoformat()}, всё локально.</p>

{dom_row('N', 'Нейротизм', 'шкала эмоциональной нестабильности',
 card(f'{posneg}:1', 'позитив : негатив', 'вся негативная лексика вместе') +
 card(full['anxiety'], 'тревога / 10 тыс. слов') + card(full['sad'], 'грусть / 10 тыс. слов') +
 card(full['anger'], 'гнев / 10 тыс. слов') + card(f'{night}%', 'ночные сообщения', '00:00–06:00'),
 'Низкому нейротизму обычно соответствуют перевес позитива и мало ночной переписки. '
 'Смотри и на рельеф: что из тревоги/грусти/гнева лидирует у тебя в языке — и совпадает ли '
 'это с фасетами теста.')}

{dom_row('E', 'Экстраверсия', 'общительность, энергия, напористость',
 card(msgs_day, 'сообщений в день', 'в среднем за всю историю') +
 card(dialogs_mo, 'активных диалогов в месяц') +
 card(f'{init}%', 'инициатива', 'доля разговоров, начатых тобой') +
 card(full['laugh'], 'смех в тексте / 10 тыс. слов'),
 'Высокая пропускная способность (сообщения, диалоги) — грубый прокси общительности. '
 'Инициатива ~50% — «зеркальный собеседник»; сильно выше — инициатор, ниже — отвечающий.')}

{dom_row('O', 'Открытость опыту', 'широта интересов, новизна',
 card(i_we, '«я» : «мы»', 'фокус на себе против общности — см. и в A') +
 card(full['n_msgs'], 'твоих сообщений с текстом'),
 'Полные индикаторы открытости (число тем, их разнообразие) требуют тематической модели — '
 'в базовом пакете их нет; см. Ngram Viewer: широта твоего словаря и «рождение слов» — '
 'хорошие косвенные признаки.')}

{dom_row('A', 'Доброжелательность', 'тёплость, уступчивость',
 card(full['polite'], 'вежливость / 10 тыс. слов', '«спасибо/извини/пожалуйста»') +
 card(inner['polite'], '…в близком круге', 'топ-10 личных чатов') +
 card(outer['polite'], '…вне близкого круга') +
 card(inner['anger'], 'гнев с близкими', f"вне круга: {outer['anger']}"),
 'Главный урок наших данных: вежливость — маркер дистанции, а не тёплости. Сравни свои '
 'три числа: если вне круга вежливость заметно выше, а гнев живёт только внутри — '
 'низкий балл A в тесте может означать «настоящий я достаётся своим», а не «я холодный».')}

{dom_row('C', 'Добросовестность', 'дисциплина, организованность',
 card(f'{night}%', 'ночная доля', 'режим как слабый прокси'),
 'Честно: переписка — плохой прибор для добросовестности; планирование и дедлайны живут '
 'вне мессенджера. Не делай выводов по этому домену из корпуса.')}

<p class="foot"><b>Дисклеймеры:</b> N=1 без популяционных норм — сравнивай только внутренние
соотношения, не абсолюты; словари эмоций прозрачные, но не валидированные; «близкий круг» —
автоматически топ-10 личных чатов по объёму (грубое приближение); в литературе языковые
предикторы личности сходятся с самоотчётом не сильнее r ≈ 0.3–0.4 (Park et al., 2015).
Это развлекательное зеркало, а не психодиагностика.</p>
</div></body></html>"""
OUT.mkdir(exist_ok=True)
(OUT / 'big5.html').write_text(html, encoding='utf-8')
print(f"out/big5.html готов (баллы теста: {'есть' if scores else 'нет'}; "
      f"вежливость круг/вне: {inner['polite']}/{outer['polite']})")
