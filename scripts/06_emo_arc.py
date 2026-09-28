#!/usr/bin/env python3
"""Chat River · шаг 6: эмоциональная дуга — средний тон твоих сообщений по месяцам
за все годы + состав эмоций по годам. Требует data/llm_valence.parquet (шаг 5).

Выход: out/emo-arc.html (самодостаточный, работает офлайн).
"""
import json
from pathlib import Path

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
OUT = ROOT / 'out'
con = duckdb.connect()

if not (DATA / 'llm_valence.parquet').exists():
    raise SystemExit('нет data/llm_valence.parquet — сначала python scripts/05_annotate_llm.py')

monthly = con.execute(f"""
    SELECT strftime(m.ts,'%Y-%m') mm, AVG(v.valence) av, COUNT(*) n,
           100.0*AVG(CASE WHEN v.val_class='positive' THEN 1 ELSE 0 END) pos,
           100.0*AVG(CASE WHEN v.val_class='negative' THEN 1 ELSE 0 END) neg
    FROM '{DATA / 'llm_valence.parquet'}' v
    JOIN '{DATA / 'messages.parquet'}' m ON v.chat_id=m.chat_id AND v.msg_id=m.msg_id
    GROUP BY 1 ORDER BY 1""").fetchall()
months = [r[0] for r in monthly]
raw = np.array([r[1] for r in monthly])
N = len(months)

def smooth(v):
    out = v.astype(float).copy()
    for i in range(len(v)):
        lo, hi = max(0, i - 1), min(len(v), i + 2)
        out[i] = v[lo:hi].mean()
    return out

sm = smooth(raw)

EMO = ['радость', 'доверие', 'предвкушение', 'удивление',
       'грусть', 'страх', 'злость', 'отвращение']
years = sorted({m[:4] for m in months})
heat = []
for e in EMO:
    row = []
    for y in years:
        r = con.execute(f"""
            SELECT ROUND(1000.0*AVG(CASE WHEN v.emotion='{e}' THEN 1 ELSE 0 END),1)
            FROM '{DATA / 'llm_valence.parquet'}' v
            JOIN '{DATA / 'messages.parquet'}' m ON v.chat_id=m.chat_id AND v.msg_id=m.msg_id
            WHERE strftime(m.ts,'%Y') = '{y}'""").fetchone()[0]
        row.append(float(r or 0))
    heat.append(row)

payload = {'months': months, 'raw': [round(float(x), 3) for x in raw],
           'sm': [round(float(x), 3) for x in sm], 'n': [int(r[2]) for r in monthly],
           'pos': [round(r[3], 1) for r in monthly], 'neg': [round(r[4], 1) for r in monthly],
           'years': years, 'emoNames': EMO, 'heat': heat}
blob = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')

page = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Эмоциональная дуга</title><style>
body{margin:0;background:#0d0d0d;color:#fff;font-family:system-ui,-apple-system,'Segoe UI',sans-serif}
.wrap{max-width:1140px;margin:0 auto;padding:34px 18px 60px}
h1{font-size:40px;margin:0 0 8px;letter-spacing:-.01em}
h2{font-size:22px;margin:44px 0 6px}
.eyebrow{font-size:13px;color:#ffb04d;text-transform:uppercase;letter-spacing:.22em;margin:0 0 10px}
.big{font-size:16px;line-height:1.55;color:#c3c2b7;max-width:74ch;margin:0 0 8px}
.note{font-size:13px;color:#898781;line-height:1.5;max-width:80ch;margin:6px 0 0}
svg{width:100%;height:auto;display:block}
.tiles{display:flex;gap:12px;flex-wrap:wrap;margin:22px 0 4px}
.tile{background:#141413;border:1px solid #292826;border-radius:14px;padding:14px 18px;min-width:180px;flex:1}
.tile .v{font-size:30px;font-weight:700}
.tile .l{font-size:12.5px;color:#898781;margin-top:3px;line-height:1.4}
.warm{color:#ffb04d}.cold{color:#4d9dff}
#tip{position:fixed;pointer-events:none;display:none;z-index:9;background:rgba(20,20,19,.97);
 border:1px solid #383835;border-radius:10px;padding:9px 12px;font-size:13px;line-height:1.5;max-width:250px}
.foot{color:#52514e;font-size:12px;line-height:1.6;margin-top:34px;max-width:92ch}
</style></head><body><div class="wrap">
<p class="eyebrow">chat river · эмо-слой</p>
<h1>Эмоциональная дуга</h1>
<p class="big">Средний эмоциональный тон твоих сообщений месяц за месяцем. Это агрегатная
кривая: отдельным оценкам сообщений верить нельзя (у прибора умеренная точность),
а форме дуги по сотням сообщений в месяц — можно.</p>
<h2>Средний тон по месяцам</h2>
<p class="note">Жирная линия — сглаживание 3 мес; тонкая — сырые средние. Шкала −5…+5,
средние живут около нуля — важен знак и форма. Наведи курсор.</p>
<svg id="arc" viewBox="0 0 1140 400"></svg>
<div class="tiles" id="tiles"></div>
<h2>Состав эмоций по годам</h2>
<p class="note">Число — сообщений с этой эмоцией на 1000 твоих. Яркость нормирована
в каждой строке на её максимум; сравнивать яркость между строками нельзя.</p>
<svg id="heat" viewBox="0 0 1140 330"></svg>
<p class="foot">Прибор: локальная LLM (промпт валидирован автором пакета на собственной
ручной разметке: κ≈0.53 — умеренная согласованность; сарказм и тонкие эмоции — слабые
места). Классы поз/нег — по порогам ≥+2 / ≤−3. Только твои непересланные сообщения.
Если разметка делалась с флагом --synthetic — это демо-суррогат, выводов не делать.</p>
</div>
<div id="tip"></div>
<script type="application/json" id="data">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const N = D.months.length;
function tempColor(t){
  const cold=[77,157,255], warm=[255,176,77], mid=[107,106,102];
  const a = t<0?cold:warm, f=Math.min(1,Math.abs(t));
  const c = a.map((x,j)=>Math.round(mid[j]+(x-mid[j])*f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
(function(){
  const W=1140,H=400,padL=46,padR=14,padT=18,padB=30;
  const absmax=Math.max(0.3,...D.raw.map(Math.abs))*1.1;
  const lo=-absmax, hi=absmax;
  const X=i=>padL+i*(W-padL-padR)/Math.max(1,N-1);
  const Y=v=>padT+(hi-v)*(H-padT-padB)/(hi-lo);
  let s='';
  const step=Math.max(0.25,Math.round(absmax*4)/8);
  for(let v=-Math.floor(absmax/step)*step; v<=absmax; v+=step){
    const vv=Math.round(v*100)/100;
    s+=`<line x1="${padL}" y1="${Y(vv)}" x2="${W-padR}" y2="${Y(vv)}" stroke="${vv===0?'#4a4a47':'#1d1c1b'}" stroke-width="${vv===0?1.4:1}"/>`;
    s+=`<text x="${padL-8}" y="${Y(vv)+4}" fill="#6b6a66" font-size="11" text-anchor="end">${vv>0?'+':''}${vv}</text>`;
  }
  D.years.forEach(y=>{
    const i=D.months.indexOf(y+'-01'); if(i<0)return;
    s+=`<line x1="${X(i)}" y1="${padT}" x2="${X(i)}" y2="${H-padB}" stroke="#232221"/>`;
    s+=`<text x="${X(i)}" y="${H-padB+18}" fill="#6b6a66" font-size="11" text-anchor="middle">${y}</text>`;
  });
  let stops='';
  const vmax=Math.max(...D.sm.map(Math.abs))||1;
  for(let i=0;i<N;i++) stops+=`<stop offset="${(i/Math.max(1,N-1)*100).toFixed(1)}%" stop-color="${tempColor(D.sm[i]/vmax)}"/>`;
  s+=`<defs><linearGradient id="g" x1="0" x2="1" y1="0" y2="0">${stops}</linearGradient></defs>`;
  let area=`M${X(0)} ${Y(0)}`, line='', rawline='';
  for(let i=0;i<N;i++){ area+=`L${X(i).toFixed(1)} ${Y(D.sm[i]).toFixed(1)}`;
    line+=(i?'L':'M')+X(i).toFixed(1)+' '+Y(D.sm[i]).toFixed(1);
    rawline+=(i?'L':'M')+X(i).toFixed(1)+' '+Y(Math.max(lo,Math.min(hi,D.raw[i]))).toFixed(1);}
  area+=`L${X(N-1)} ${Y(0)}Z`;
  s+=`<path d="${area}" fill="url(#g)" opacity=".28"/>`;
  s+=`<path d="${rawline}" fill="none" stroke="#6b6a66" stroke-width="1" opacity=".5"/>`;
  s+=`<path d="${line}" fill="none" stroke="url(#g)" stroke-width="2.4"/>`;
  s+=`<line id="cross" x1="0" y1="${padT}" x2="0" y2="${H-padB}" stroke="#fff" stroke-width="1" opacity="0"/>`;
  s+=`<rect x="${padL}" y="${padT}" width="${W-padL-padR}" height="${H-padT-padB}" fill="transparent" id="hv"/>`;
  const svg=document.getElementById('arc'); svg.innerHTML=s;
  const tip=document.getElementById('tip'), cross=svg.querySelector('#cross');
  svg.querySelector('#hv').addEventListener('mousemove',ev=>{
    const r=svg.getBoundingClientRect(), sx=W/r.width;
    const i=Math.max(0,Math.min(N-1,Math.round(((ev.clientX-r.left)*sx-padL)/((W-padL-padR)/Math.max(1,N-1)))));
    cross.setAttribute('x1',X(i));cross.setAttribute('x2',X(i));cross.setAttribute('opacity','.35');
    tip.style.display='block';
    tip.style.left=Math.min(window.innerWidth-260,ev.clientX+14)+'px';
    tip.style.top=(ev.clientY+14)+'px';
    tip.innerHTML=`<b>${D.months[i]}</b><br>средний тон <b style="color:${tempColor(D.sm[i]/vmax)}">${D.raw[i]>0?'+':''}${D.raw[i].toFixed(2)}</b><br>`+
      `сообщений: ${D.n[i]} · поз ${D.pos[i]}% · нег ${D.neg[i]}%`;
  });
  svg.querySelector('#hv').addEventListener('mouseleave',()=>{tip.style.display='none';cross.setAttribute('opacity','0');});
})();
(function(){
  let lo=0, hi=0, last=N-1;
  D.sm.forEach((v,i)=>{ if(v<D.sm[lo])lo=i; if(v>D.sm[hi])hi=i; });
  document.getElementById('tiles').innerHTML=`
   <div class="tile"><div class="v cold">${D.sm[lo].toFixed(2)}</div>
    <div class="l">самый холодный месяц — ${D.months[lo]}</div></div>
   <div class="tile"><div class="v warm">+${D.sm[hi].toFixed(2)}</div>
    <div class="l">самый тёплый — ${D.months[hi]}</div></div>
   <div class="tile"><div class="v">${D.raw[last]>0?'+':''}${D.raw[last].toFixed(2)}</div>
    <div class="l">последний месяц корпуса — ${D.months[last]}</div></div>`;
})();
(function(){
  const W=1140,H=330,padL=118,padT=30;
  const ny=D.years.length, ne=D.emoNames.length;
  const cw=(W-padL-8)/ny, ch=(H-padT-8)/ne;
  let s='';
  D.years.forEach((y,j)=>{ s+=`<text x="${padL+cw*(j+0.5)}" y="${padT-8}" fill="#898781" font-size="11" text-anchor="middle">${y}</text>`; });
  D.emoNames.forEach((em,i)=>{
    s+=`<text x="${padL-8}" y="${padT+ch*(i+0.62)}" fill="#c3c2b7" font-size="12.5" text-anchor="end">${em}</text>`;
    const rowmax=Math.max(...D.heat[i])||1;
    D.years.forEach((y,j)=>{
      const t=D.heat[i][j]/rowmax;
      const base=[20,19,18], gold=[255,176,77];
      const c=base.map((x,k)=>Math.round(x+(gold[k]-x)*t));
      s+=`<rect x="${(padL+cw*j+1).toFixed(1)}" y="${(padT+ch*i+1).toFixed(1)}" width="${(cw-2).toFixed(1)}" height="${(ch-2).toFixed(1)}" rx="4" fill="rgb(${c[0]},${c[1]},${c[2]})"/>`;
      s+=`<text x="${padL+cw*(j+0.5)}" y="${padT+ch*(i+0.64)}" fill="${t>0.55?'#141413':'#898781'}" font-size="10.5" text-anchor="middle">${D.heat[i][j].toFixed(0)}</text>`;
    });
  });
  document.getElementById('heat').innerHTML=s;
})();
</script></body></html>"""

OUT.mkdir(exist_ok=True)
(OUT / 'emo-arc.html').write_text(page.replace('__DATA__', blob), encoding='utf-8')
print(f'готово: out/emo-arc.html ({N} месяцев, {len(years)} лет)')
