#!/usr/bin/env python3
"""Chat River · шаг 5 (уровни 2–3): эмоциональная разметка ТВОИХ сообщений через LLM.

Каждое твоё сообщение получает: валентность −5…+5, эмоцию (8 базовых + «нет явной»),
флаг сарказма. Нужна для эмоциональной дуги (шаг 6) и настоящей температуры реки.

УРОВЕНЬ 2 — локально (по умолчанию; ничего не покидает компьютер):
  python scripts/05_annotate_llm.py
Нужен LM Studio (lmstudio.ai) с моделью gemma-3-12b-it (≈8 ГБ; на ней промпт
валидирован автором: κ≈0.53 против ручной разметки — умеренная согласованность,
потолок одиночного кодировщика) и включённым Local Server. Скрипт сам найдёт модель.
Скорость на Mac M-серии с 16 ГБ: ~0.5–1.5 сообщ/с → 10 тыс. сообщений за вечер,
100 тыс. — сутки-трое чистой работы. Чекпоинт после каждого ответа: прерывай и
перезапускай сколько угодно — удобно гонять ночами по частям.

УРОВЕНЬ 3 — облако (быстро: 5–12 сообщ/с, ~$2–4 за 100 тыс. сообщений;
НО твои сообщения уходят провайдеру модели — по одному, без реплик собеседников;
включай только осознанно):
  export CHATRIVER_LLM_URL="https://openrouter.ai/api/v1/chat/completions"
  export CHATRIVER_LLM_MODEL="google/gemma-3-12b-it"
  export CHATRIVER_LLM_KEY="sk-or-..."
  python scripts/05_annotate_llm.py
При заданном ключе запросы идут в 8 параллельных потоков (CHATRIVER_LLM_WORKERS).
Совет: в настройках OpenRouter (Privacy) запрети провайдеров, обучающихся на данных,
а ключ сделай временным и отзови после прогона.

Демо-режим (без LLM, суррогат по словарям + шум — ТОЛЬКО для примера):
  python scripts/05_annotate_llm.py --synthetic

Выход: data/llm_valence.parquet + чекпоинт data/llm-valence-raw.jsonl.
"""
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "llm-valence-raw.jsonl"
URL = os.environ.get("CHATRIVER_LLM_URL", "http://127.0.0.1:1234/v1/chat/completions")
MODEL = os.environ.get("CHATRIVER_LLM_MODEL", "")
KEY = os.environ.get("CHATRIVER_LLM_KEY", "")
PAUSE = float(os.environ.get("CHATRIVER_LLM_PAUSE", "0" if not KEY else "0"))
WORKERS = int(os.environ.get("CHATRIVER_LLM_WORKERS", "8" if KEY else "4"))
EMO = [
    "радость",
    "доверие",
    "страх",
    "удивление",
    "грусть",
    "отвращение",
    "злость",
    "предвкушение",
    "нет явной",
]

# Промпт зафиксирован в валидированной редакции v2 (якорение нейтральности + few-shot).
# Написан по-русски; Gemma мультиязычна — для не-русских корпусов работает, но
# валидация автора проводилась на русском.
PROMPT = (
    "Оцени сообщение из личной переписки в Telegram. ВАЖНО: большинство бытовых сообщений "
    "(логистика, факты, вопросы по делу, ссылки, короткие реплики) НЕЙТРАЛЬНЫ: valence 0, "
    'emotion "нет явной", sarcasm false. Ненулевую оценку ставь только при ЯВНЫХ '
    "эмоциональных маркерах в самом тексте. Сарказм отмечай только при очевидной иронии.\n"
    "Примеры:\n"
    '«буду через 20 минут, купи хлеба» -> {"valence": 0, "emotion": "нет явной", "sarcasm": false}\n'
    '«скинь ссылку на тот документ» -> {"valence": 0, "emotion": "нет явной", "sarcasm": false}\n'
    '«ура, наконец-то получилось!!» -> {"valence": 4, "emotion": "радость", "sarcasm": false}\n'
    '«меня это уже реально бесит» -> {"valence": -3, "emotion": "злость", "sarcasm": false}\n'
    'Ответь СТРОГО одним JSON-объектом без пояснений: {"valence": целое от -5 до 5, '
    '"emotion": одна из ["радость","доверие","страх","удивление","грусть","отвращение",'
    '"злость","предвкушение","нет явной"], "sarcasm": true/false}.\n'
    "Сообщение: «{msg}»"
)
JSON_RE = re.compile(r"\{[^{}]*\}")

POS_RE = re.compile(
    r"\b(рад\w{0,3}|круто|клево|классно|здорово|отлично|прекрасн\w+|люблю|обожаю|счастлив\w*|кайф\w*|спасибо)\b",
    re.I,
)
NEG_RE = re.compile(
    r"\b(трево\w+|боюсь|страшно|страх\w*|пережива\w+|бесит\w*|злюсь|злит\w*|ненави\w+|раздража\w+|грустн?\w*|тоск\w+|печал\w+|устал\w*|одинок\w+)\b",
    re.I,
)


def load_messages():
    import duckdb

    con = duckdb.connect()
    return con.execute(
        f"""
        SELECT chat_id, msg_id, text FROM '{DATA / 'messages.parquet'}'
        WHERE is_mine AND NOT is_forwarded AND text IS NOT NULL AND length(trim(text)) > 0
        ORDER BY chat_id, msg_id"""
    ).fetchall()


def detect_model():
    global MODEL
    if MODEL:
        return
    base = URL.rsplit("/chat/completions", 1)[0]
    req = urllib.request.Request(
        base + "/models", headers={"Authorization": f"Bearer {KEY}"} if KEY else {}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        models = json.load(r)["data"]
    chat_models = [m["id"] for m in models if "embed" not in m["id"]]
    if not chat_models:
        sys.exit(
            "В LM Studio не загружена ни одна модель — скачай gemma-3-12b-it и включи сервер."
        )
    MODEL = chat_models[0]
    print(f"модель: {MODEL}", flush=True)


def ask(text):
    body = json.dumps(
        {
            "model": MODEL,
            "temperature": 0,
            "max_tokens": 90,
            "messages": [{"role": "user", "content": PROMPT.replace("{msg}", text)}],
        }
    ).encode()
    headers = {"Content-Type": "application/json"}
    if KEY:
        headers["Authorization"] = f"Bearer {KEY}"
    req = urllib.request.Request(URL, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.load(r)
    content = out["choices"][0]["message"]["content"]
    m = JSON_RE.search(content)
    if not m:
        raise ValueError(f"нет JSON в ответе: {content[:100]!r}")
    obj = json.loads(m.group(0))
    v = max(-5, min(5, int(obj["valence"])))
    e = obj.get("emotion")
    if e not in EMO:
        e = "нет явной"
    return {"valence": v, "emotion": e, "sarcasm": bool(obj.get("sarcasm"))}


def synthetic(text, rnd):
    """Суррогат для демо: словари + шум. НЕ ИСПОЛЬЗУЙ для реальных выводов."""
    p, n = len(POS_RE.findall(text.lower())), len(NEG_RE.findall(text.lower()))
    v = max(-5, min(5, round((p - n) * 2 + rnd.gauss(0, 0.8))))
    if abs(v) < 2:
        v = 0
    emo = "нет явной"
    if v >= 2:
        emo = rnd.choice(["радость", "доверие", "предвкушение"])
    elif v <= -2:
        emo = rnd.choice(["грусть", "злость", "страх"])
    return {"valence": v, "emotion": emo, "sarcasm": rnd.random() < 0.02}


def main():
    syn = "--synthetic" in sys.argv
    rows = load_messages()
    done = set()
    if RAW.exists():
        for line in RAW.read_text(encoding="utf-8").splitlines():
            try:
                o = json.loads(line)
                done.add((o["c"], o["m"]))
            except Exception:
                pass
    todo = [(c, m, t) for c, m, t in rows if (c, m) not in done]
    print(
        f"твоих сообщений: {len(rows)}, уже размечено {len(done)}, осталось {len(todo)}",
        flush=True,
    )

    if syn:
        import random

        rnd = random.Random(7)
        with open(RAW, "a", encoding="utf-8") as f:
            for c, m, t in todo:
                f.write(
                    json.dumps(
                        {"c": c, "m": m, **synthetic(t, rnd)}, ensure_ascii=False
                    )
                    + "\n"
                )
        print(
            "⚠ суррогатная разметка (--synthetic): только для демо, не для выводов",
            flush=True,
        )
    else:
        detect_model()
        from concurrent.futures import ThreadPoolExecutor
        from threading import Lock

        t0 = time.time()
        state = {"done": 0, "fails": 0}
        lock = Lock()

        def work(job):
            c, m, t = job
            for attempt in range(3):
                try:
                    res = ask(t)
                    with lock:
                        with open(RAW, "a", encoding="utf-8") as f:
                            f.write(
                                json.dumps({"c": c, "m": m, **res}, ensure_ascii=False)
                                + "\n"
                            )
                        state["done"] += 1
                        if state["done"] % 200 == 0:
                            rate = state["done"] / (time.time() - t0)
                            eta = (len(todo) - state["done"]) / rate / 3600
                            print(
                                f"{state['done']}/{len(todo)}  {rate:.1f} сообщ/с  "
                                f"ETA {eta:.1f} ч",
                                flush=True,
                            )
                    break
                except Exception:
                    if attempt == 2:
                        with lock:
                            state["fails"] += 1
                    else:
                        time.sleep(5 * (attempt + 1))
            time.sleep(PAUSE)

        if WORKERS > 1:
            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                list(ex.map(work, todo))
        else:
            for job in todo:
                work(job)
        if state["fails"]:
            print(
                f"пропущено после ретраев: {state['fails']} "
                f"(перезапусти скрипт — чекпоинт продолжит)",
                flush=True,
            )

    # jsonl → parquet (дедуп по ключу; классы по калиброванным порогам автора: ≤−3 / ≥+2)
    best = {}
    for line in RAW.read_text(encoding="utf-8").splitlines():
        o = json.loads(line)
        best[(o["c"], o["m"])] = o
    recs = [
        {
            "chat_id": c,
            "msg_id": m,
            "valence": o["valence"],
            "emotion": o["emotion"],
            "sarcasm": o["sarcasm"],
            "val_class": (
                "negative"
                if o["valence"] <= -3
                else ("positive" if o["valence"] >= 2 else "neutral")
            ),
        }
        for (c, m), o in best.items()
    ]
    pq.write_table(
        pa.Table.from_pylist(recs), DATA / "llm_valence.parquet", compression="zstd"
    )
    print(
        f"готово: data/llm_valence.parquet ({len(recs)} строк). Дальше: python scripts/06_emo_arc.py"
    )


if __name__ == "__main__":
    main()
