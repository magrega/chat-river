#!/usr/bin/env python3
"""Создаёт demo/result.json — синтетический мини-экспорт для проверки пакета без данных.

В демо-жизнь вшит сюжет, чтобы река выглядела как настоящая:
  · Алекс — старый друг: мощное русло в начале, пересыхает к концу первого года,
    короткое эхо-возвращение в конце;
  · Мария — константа: ровное русло через все три года;
  · Илья — дружба-вспышка: появляется, разрастается до главного русла и обрывается;
  · Соня — роман: рождается в середине, становится широким тёплым руслом до конца;
  · «Банда 🏕» — новая компания: групповой чат, врывается на третьем году;
  · Дед — эпизодический: три коротких всплеска вокруг семейных дат.
Плюс глобальная дуга настроения (холодное начало → тёплое плато → просадка в конце).
Все имена и тексты вымышлены."""
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
random.seed(7)

WORDS = ('привет как дела работа проект встреча завтра лодка поход кино '
         'идея код данные книга музыка чай извини пожалуйста ахаха план отчет спорт '
         'бег горы море фильм ужин совет').split()
POS_W = 'круто люблю здорово отлично классно счастлив рад кайф'.split()
NEG_W = 'устал грустно бесит тревожно страшно тоска раздражает одиноко'.split()

DAYS = 1095  # три года: 2023-01-01 — 2025-12-31
START = datetime(2023, 1, 1, 9, 0)


def mood(day):
    """Глобальная дуга: холодное начало → тёплое плато → просадка в конце."""
    x = day / DAYS
    if x < 0.25:
        return -0.5 + x * 3.4
    if x < 0.8:
        return 0.35
    return 0.35 - (x - 0.8) * 3.0


def bump(day, center, width, height):
    return height * math.exp(-((day - center) / width) ** 2)


def ramp(day, a, b):
    """0 до a, линейно до 1 к b, дальше 1."""
    if day <= a:
        return 0.0
    if day >= b:
        return 1.0
    return (day - a) / (b - a)


# интенсивность каждого русла (ожидаемых сообщений в день) по дням
CAST = [
    # (имя, id чата, тип, отправители-не-я, функция интенсивности)
    ('Алекс', 111001, 'personal_chat', ['user111'],
     lambda d: 3.2 * (1 - ramp(d, 250, 420)) + bump(d, 980, 18, 1.6) + 0.05),
    ('Мария', 111002, 'personal_chat', ['user222'],
     lambda d: 1.1 + 0.4 * ramp(d, 850, 1000)),
    ('Илья', 111003, 'personal_chat', ['user333'],
     lambda d: 3.0 * ramp(d, 230, 400) * (1 - ramp(d, 820, 870)) + 0.02),
    ('Соня', 111004, 'personal_chat', ['user444'],
     lambda d: 4.0 * ramp(d, 490, 620)),
    ('Банда 🏕', 222001, 'private_group', ['user555', 'user666', 'user777'],
     lambda d: 3.5 * ramp(d, 610, 730)),
    ('Дед', 111005, 'personal_chat', ['user888'],
     lambda d: bump(d, 100, 22, 1.4) + bump(d, 465, 22, 1.4) + bump(d, 830, 22, 1.4)),
]


def make_msg(mid, ts, sender, me_id, m):
    n = random.randint(2, 12)
    words = random.choices(WORDS, k=n)
    r = random.random()
    if r < 0.15 + max(0.0, m) * 0.5:
        words.append(random.choice(POS_W))
    if r > 1 - (0.08 + max(0.0, -m) * 0.6):
        words.append(random.choice(NEG_W))
    return {'id': mid, 'type': 'message', 'date': ts.strftime('%Y-%m-%dT%H:%M:%S'),
            'from': 'Me' if sender == me_id else sender,
            'from_id': sender, 'text': ' '.join(words), 'text_entities': []}


me = 999001
me_id = f'user{me}'
chats = [{'name': None, 'type': 'saved_messages', 'id': me, 'messages': []}]
mid = 1
for name, cid, ctype, others, env in CAST:
    msgs = []
    for d in range(DAYS):
        lam = env(d) * random.uniform(0.5, 1.5)
        count = int(lam) + (1 if random.random() < lam - int(lam) else 0)
        t2 = START + timedelta(days=d)
        for _ in range(count):
            t2 += timedelta(minutes=random.randint(2, 240))
            mine = random.random() < (0.5 if ctype == 'personal_chat' else 0.35)
            sender = me_id if mine else random.choice(others)
            # у Сони русло теплее глобальной дуги, у Ильи финал — холоднее
            m = mood(d)
            if name == 'Соня':
                m += 0.25
            if name == 'Илья' and d > 760:
                m -= 0.5
            msgs.append(make_msg(mid, t2, sender, me_id, m))
            mid += 1
    chats.append({'name': name, 'type': ctype, 'id': cid, 'messages': msgs})

out = ROOT / 'demo'
out.mkdir(exist_ok=True)
with open(out / 'result.json', 'w', encoding='utf-8') as f:
    json.dump({'about': 'demo', 'chats': {'list': chats}}, f, ensure_ascii=False)
print(f'demo/result.json: {mid - 1} сообщений, {len(chats)} чатов, {DAYS} дней')
