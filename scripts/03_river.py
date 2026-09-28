#!/usr/bin/env python3
"""«Река общения» v3: температура воды (эмоциональный баланс вдоль русла),
события на берегу, экспорт PNG-постера, селектор любого чата, плавный автосплав.
Только собственные сообщения (R1). Выход: ../story-river.html
"""
import json
import re
from pathlib import Path

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / 'data'
OUT = ROOT / 'out'
con = duckdb.connect()
URL = re.compile(r'(?:https?://|www\.)\S+', re.IGNORECASE)
POS = re.compile(r'\b(рад\w{0,3}|круто|клево|классно|здорово|отлично|прекрасн\w+|люблю|обожаю|счастлив\w*|кайф\w*)\b', re.I)
NEG = re.compile(r'\b(трево\w+|боюсь|страшно|страх\w*|паник\w*|пережива\w+|нервнича\w+|бесит\w*|злюсь|злит\w*|ненави\w+|раздража\w+|грустн?\w*|тоск\w+|печал\w+|депрес\w+|устал\w*|выгор\w+|одинок\w+)\b', re.I)
TOK = re.compile(r'[а-яёa-z0-9]+')

rows = con.execute(f"""
  SELECT strftime(m.ts,'%Y-%m') mm, m.chat_id, c.name, count(*) n
  FROM '{HERE}/messages.parquet' m JOIN '{HERE}/chats.parquet' c USING (chat_id)
  WHERE m.is_mine AND NOT m.is_forwarded
    AND c.type IN ('personal_chat','private_group','private_supergroup','bot_chat','saved_messages')
  GROUP BY 1,2,3""").fetchall()
months = sorted({r[0] for r in rows})
mi = {m: i for i, m in enumerate(months)}
N = len(months)
tot = np.zeros(N)
per_chat, names = {}, {}
for mm, cid, name, n in rows:
    tot[mi[mm]] += n
    per_chat.setdefault(cid, np.zeros(N))[mi[mm]] += n
    names[cid] = name or '(без имени)'

top8 = sorted(per_chat, key=lambda c: -float((per_chat[c] / np.maximum(tot, 1)).sum()))[:8]
other = tot - sum(per_chat[c] for c in top8)

def smooth(v):
    out = v.astype(float).copy()
    for i in range(len(v)):
        lo, hi = max(0, i - 1), min(len(v), i + 2)
        out[i] = v[lo:hi].mean()
    return out

series = [{'label': names[c], 'vals': smooth(per_chat[c]).round(1).tolist(),
           'raw': per_chat[c].astype(int).tolist()} for c in top8]
series.append({'label': 'остальные', 'vals': smooth(other).round(1).tolist(),
               'raw': other.astype(int).tolist()})

# сэмплы, истоки и температура (эмоциональный баланс по месяцам) для топ-8
samples, origins, temps = {}, {}, {}
for k, cid in enumerate(top8):
    msgs = con.execute(f"""
      SELECT strftime(ts,'%Y-%m') mm, text FROM '{HERE}/messages.parquet'
      WHERE chat_id = {cid} AND is_mine AND NOT is_forwarded AND n_tokens > 0
      ORDER BY ts""").fetchall()
    bym, pos_m, neg_m, tok_m = {}, {}, {}, {}
    for mm, txt in msgs:
        low = txt.lower().replace('ё', 'е')
        tok_m[mm] = tok_m.get(mm, 0) + len(TOK.findall(low))
        pos_m[mm] = pos_m.get(mm, 0) + len(POS.findall(low))
        neg_m[mm] = neg_m.get(mm, 0) + len(NEG.findall(low))
        t = URL.sub('', txt).strip()
        if 8 <= len(t) <= 220:
            bym.setdefault(mm, []).append(t)
    smp = {}
    for mm, lst in bym.items():
        picks = [lst[0]] if len(lst) == 1 else [lst[0], lst[len(lst) // 2]]
        smp[mi[mm]] = [p[:130] + ('…' if len(p) > 130 else '') for p in picks]
    samples[k] = smp
    if msgs:
        origins[k] = {'m': mi[msgs[0][0]], 'text': URL.sub('', msgs[0][1]).strip()[:140]}
    bal = np.zeros(N)
    for mm in tok_m:
        bal[mi[mm]] = (pos_m[mm] - neg_m[mm]) * 10000 / max(tok_m[mm], 300)
    bal = smooth(bal)
    vmax = np.abs(bal).max() or 1
    temps[k] = np.clip(bal / vmax, -1, 1).round(2).tolist()

# дополнительные чаты для селектора: топ-120 по моим сообщениям вне топ-8
extra_ids = sorted((c for c in per_chat if c not in top8),
                   key=lambda c: -per_chat[c].sum())[:120]
extra = [{'label': names[c], 'vals': smooth(per_chat[c]).round(1).tolist(),
          'raw': per_chat[c].astype(int).tolist()} for c in extra_ids
         if per_chat[c].sum() >= 30]

eras = []
events = []

payload = {'months': months, 'series': series, 'samples': samples, 'origins': origins,
           'temps': temps, 'extra': extra, 'eras': [], 'events': [],
           'colors': ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181',
                      '#00a300', '#9085e9', '#e66767', '#4a4a47'],
           'extraColors': ['#52c7d8', '#b8a1ff', '#8fd14f', '#ff9d9d']}
blob = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')

page = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Река общения</title><style>
body{margin:0;background:#0d0d0d;color:#fff;font-family:system-ui,-apple-system,'Segoe UI',sans-serif}
.wrap{max-width:1140px;margin:0 auto;padding:34px 18px 60px}
h1{font-size:42px;margin:0 0 8px;letter-spacing:-.01em}
.eyebrow{font-size:13px;color:#3987e5;text-transform:uppercase;letter-spacing:.22em;margin:0 0 10px}
.big{font-size:16px;line-height:1.55;color:#c3c2b7;max-width:70ch;margin:0 0 8px}
.legend{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 4px;align-items:center}
.chip{font-size:13px;padding:5px 12px;border-radius:999px;border:1px solid #383835;color:#c3c2b7;cursor:pointer;background:transparent;display:flex;align-items:center;gap:7px}
.chip .sw{width:10px;height:10px;border-radius:3px}
.chip:hover{border-color:#898781;color:#fff}
.chip.active{border-color:#fff;color:#fff;background:rgba(255,255,255,.06)}
.chip.tool{border-color:#1c5cab;color:#86b6ef}
.chip.tool.on{border-color:#3987e5;color:#fff;background:rgba(57,135,229,.12)}
.tools{display:flex;gap:8px;flex-wrap:wrap;margin:4px 0 8px;align-items:center}
.tools input{background:#141413;border:1px solid #383835;color:#fff;border-radius:8px;padding:6px 10px;font-size:13px;width:230px}
#riverbox{position:relative}
#river{width:100%;height:auto;display:block}
.stream{transition:opacity .5s ease}
.stream.clickable{cursor:pointer}
.dim{opacity:.13}
.lift{opacity:1;filter:drop-shadow(0 0 10px rgba(255,255,255,.3))}
#card{position:absolute;pointer-events:none;display:none;z-index:5;background:rgba(20,20,19,.96);
 border:1px solid #383835;border-radius:12px;padding:12px 14px;max-width:330px;box-shadow:0 6px 24px rgba(0,0,0,.6);
 transition:left .9s linear, top .5s ease}
#card.jump{transition:none}
#card .who{font-weight:700;font-size:14px}
#card .when{color:#898781;font-size:12px;margin:2px 0 6px}
#card .msg{font-size:13px;line-height:1.5;color:#c3c2b7;border-left:2px solid #383835;padding-left:9px;margin:7px 0;font-style:italic}
#card .stat{font-size:12px;color:#898781}
#cursorline{transition:transform 1.35s linear;pointer-events:none}
.hint{font-size:13px;color:#898781;margin:8px 0 0}
.foot{color:#52514e;font-size:12px;line-height:1.6;margin-top:20px;max-width:86ch}
</style></head><body><div class="wrap">
<p class="eyebrow">река общения</p>
<h1>__YEARS__ — одна река</h1>
<p class="big">Клик по руслу — поток на передний план. Курсор вдоль течения — сообщения из
прошлого. «Проплыть» — медленный сплав от истока. «Температура» красит выбранное русло
эмоциональным балансом той поры: тёплое золото — светлые месяцы, холодная синь — тяжёлые.
</p>
<div class="legend" id="legend"></div>
<div class="tools">
<button class="chip tool" id="tempbtn">🌡 температура</button>
<button class="chip tool" id="playbtn">▶ проплыть</button>
<button class="chip tool" id="posterbtn">🖼 постер PNG</button>
<input list="chatlist" id="chatpick" placeholder="добавить чат в реку…">
<datalist id="chatlist"></datalist>
</div>
<div id="riverbox">
<svg id="river" viewBox="0 0 1140 560"></svg>
<div id="card"></div>
</div>
<p class="hint" id="status">Ничего не выбрано — кликни на течение.</p>
<p class="foot">Все данные — локальные; цитаты в подсказках — только твои собственные сообщения.
Температура — прозрачные эмо-словари по моим сообщениям в этом чате, нормировка на максимум
русла. Сглаживание 3 мес. Селектор добавляет любой из топ-120 чатов (до 4 сразу).</p>
</div>
<script type="application/json" id="data">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const N = D.months.length;
const W = 1140, H = 560, ML = 16, MR = 16, MT = 46, MB = 30;
const X = i => ML + (W-ML-MR) * i / (N-1);
const svg = document.getElementById('river');
const card = document.getElementById('card');
const box = document.getElementById('riverbox');
const statusEl = document.getElementById('status');
let selected = null, playTimer = null, tempOn = false, evOn = true;
let added = [];   // индексы в D.extra

function activeSeries(){
  const extras = added.map((ei,j)=>({...D.extra[ei], color:D.extraColors[j%D.extraColors.length], extra:true}));
  const base = D.series.map((s,k)=>({...s, color:D.colors[k], k}));
  return [...base.slice(0,-1), ...extras, base[base.length-1]];
}
let AS = activeSeries();

function recompute(){
  AS = activeSeries();
  const S = AS.length;
  const sums = Array.from({length:N},(_,i)=>AS.reduce((a,s)=>a+s.vals[i],0));
  const vmax = Math.max(...sums);
  const Y = v => H/2 - v * (H-MT-MB) / vmax;
  const base = sums.map(v=>-v/2);
  const lo=[], hi=[];
  let cum = base.slice();
  for (let k=0;k<S;k++){ lo.push(cum.slice()); cum = cum.map((v,i)=>v+AS[k].vals[i]); hi.push(cum.slice()); }
  return {S, sums, Y, lo, hi};
}
let G = recompute();

function catmull(pts){
  if (pts.length<3) return 'M'+pts.map(p=>p[0]+' '+p[1]).join('L');
  let d = 'M'+pts[0][0].toFixed(1)+' '+pts[0][1].toFixed(1);
  for (let i=0;i<pts.length-1;i++){
    const p0=pts[Math.max(0,i-1)], p1=pts[i], p2=pts[i+1], p3=pts[Math.min(pts.length-1,i+2)];
    d += 'C'+(p1[0]+(p2[0]-p0[0])/6).toFixed(1)+' '+(p1[1]+(p2[1]-p0[1])/6).toFixed(1)+' '
           +(p2[0]-(p3[0]-p1[0])/6).toFixed(1)+' '+(p2[1]-(p3[1]-p1[1])/6).toFixed(1)+' '
           +p2[0].toFixed(1)+' '+p2[1].toFixed(1);
  }
  return d;
}

function tempColor(t){ // t ∈ [-1,1]: холод → тепло
  const cold=[77,157,255], warm=[255,176,77], mid=[107,106,102];
  const a = t<0?cold:warm, f=Math.abs(t);
  const c = a.map((x,j)=>Math.round(mid[j]+(x-mid[j])*f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

function svgBody(inlineOpacity){
  const {S, sums, Y, lo, hi} = G;
  let defs = '', el = '';
  if (tempOn && selected!=null && !AS[selected].extra && D.temps[AS[selected].k]!==undefined){
    const t = D.temps[AS[selected].k];
    let stops = '';
    for (let i=0;i<N;i+=2)
      stops += `<stop offset="${(i/(N-1)*100).toFixed(1)}%" stop-color="${tempColor(t[i])}"/>`;
    defs = `<defs><linearGradient id="temp" x1="0" x2="1" y1="0" y2="0">${stops}</linearGradient></defs>`;
  }
  for (const e of D.eras){
    const xm=(X(e.a)+X(e.b))/2;
    el += `<line x1="${X(e.a).toFixed(1)}" y1="${MT-8}" x2="${X(e.a).toFixed(1)}" y2="${H-MB}" stroke="#2c2c2a"/>`;
    el += `<text x="${xm.toFixed(0)}" y="${MT-18}" text-anchor="middle" font-size="10.5" fill="#6b6a66" transform="rotate(-20 ${xm.toFixed(0)} ${MT-18})">${e.label}</text>`;
  }
  for (let k=0;k<S;k++){
    const top = hi[k].map((v,i)=>[X(i),Y(v)]);
    const bot = lo[k].map((v,i)=>[X(i),Y(v)]).reverse();
    const d = catmull(top)+catmull(bot).replace(/^M/,'L')+'Z';
    const isSel = selected===k;
    const fill = (isSel && tempOn && defs) ? 'url(#temp)' : AS[k].color;
    let attrs = `class="stream clickable${selected==null?'':(isSel?' lift':' dim')}" data-k="${k}"`;
    if (inlineOpacity) attrs = `fill-opacity="${selected==null?1:(isSel?1:0.13)}"`;
    el += `<path ${attrs} d="${d}" fill="${fill}" stroke="#0d0d0d" stroke-width="0.8"/>`;
  }
  for (let k=0;k<S-1;k++){
    if (selected!=null && selected!==k) continue;
    const v = AS[k].vals;
    let pi=0; v.forEach((x,i)=>{ if(x>v[pi]) pi=i; });
    if (v[pi]/Math.max(1,sums[pi]) < 0.12 && selected!==k) continue;
    const ym = (Y(lo[k][pi])+Y(hi[k][pi]))/2;
    el += `<text x="${X(pi).toFixed(0)}" y="${ym.toFixed(0)}" text-anchor="middle" font-size="13" font-weight="700" fill="#fff" style="text-shadow:0 0 8px rgba(0,0,0,.9);pointer-events:none">${AS[k].label}</text>`;
  }
  if (selected!=null && !AS[selected].extra && D.origins[AS[selected].k]){
    const o = D.origins[AS[selected].k];
    const yo = (Y(lo[selected][o.m])+Y(hi[selected][o.m]))/2;
    el += `<circle cx="${X(o.m).toFixed(1)}" cy="${yo.toFixed(1)}" r="5" fill="#fff" style="pointer-events:none"/>`;
  }
  if (evOn) D.events.forEach((ev,ei)=>{
    const yShore = Y(-sums[ev.m]/2)+14;
    el += `<g class="evflag" data-ev="${ei}" style="cursor:pointer">`+
          `<circle cx="${X(ev.m).toFixed(1)}" cy="${yShore-4}" r="14" fill="transparent"/>`+
          `<line x1="${X(ev.m).toFixed(1)}" y1="${yShore-10}" x2="${X(ev.m).toFixed(1)}" y2="${yShore+4}" stroke="#c3c2b7" stroke-width="1"/>`+
          `<path d="M${X(ev.m).toFixed(1)} ${yShore-10} l9 3.5 l-9 3.5Z" fill="#c3c2b7"/></g>`;
  });
  for (let i=0;i<N;i++)
    if (D.months[i].endsWith('-01') && +D.months[i].slice(0,4)%2===0)
      el += `<text x="${X(i).toFixed(0)}" y="${H-8}" text-anchor="middle" font-size="11" fill="#898781">${D.months[i].slice(0,4)}</text>`;
  return defs+el;
}

function draw(){
  svg.innerHTML = svgBody(false) +
    `<rect id="cursorline" x="0" y="${MT}" width="1.2" height="${H-MT-MB}" fill="#fff" opacity="0"/>`;
  svg.querySelectorAll('.stream').forEach(p=>{
    p.addEventListener('click', ev=>{ ev.stopPropagation(); select(+p.dataset.k===selected?null:+p.dataset.k); });
  });
  svg.querySelectorAll('.evflag').forEach(g=>{
    const ev = D.events[+g.dataset.ev];
    g.addEventListener('mouseenter', e=>{
      if (playTimer) return;
      card.classList.add('jump');
      card.innerHTML = `<div class="who" style="color:#c3c2b7">⚑ ${ev.label}</div>`+
        `<div class="when">${MRU[D.months[ev.m].slice(5)]} ${D.months[ev.m].slice(0,4)}</div>`;
      card.style.display='block';
      const r = box.getBoundingClientRect();
      let tx = e.clientX - r.left + 16;
      if (tx + 340 > r.width) tx = e.clientX - r.left - 348;
      card.style.left = tx+'px';
      card.style.top = (e.clientY - r.top - 70)+'px';
      e.stopPropagation();
    });
    g.addEventListener('mousemove', e=>e.stopPropagation());
    g.addEventListener('mouseleave', ()=>{ if(!playTimer) card.style.display='none'; });
    g.addEventListener('click', e=>e.stopPropagation());
  });
}

const MRU={'01':'январь','02':'февраль','03':'март','04':'апрель','05':'май','06':'июнь','07':'июль','08':'август','09':'сентябрь','10':'октябрь','11':'ноябрь','12':'декабрь'};
function showCard(k,i,px,py,jump){
  const s = AS[k], mm = D.months[i];
  let msgs='';
  if (!s.extra){
    const smp=(D.samples[s.k]||{})[i];
    if (smp) for (const t of smp) msgs+=`<div class="msg">«${t.replace(/</g,'&lt;')}»</div>`;
    else if (k<G.S-1) msgs='<div class="stat" style="margin-top:6px">в этом месяце тишина</div>';
  } else msgs='<div class="stat" style="margin-top:6px">цитаты доступны для топ-8</div>';
  const share = G.sums[i]?Math.round(s.vals[i]*100/G.sums[i]):0;
  card.classList.toggle('jump', !!jump);
  card.innerHTML = `<div class="who" style="color:${s.color}">${s.label}</div>`+
    `<div class="when">${MRU[mm.slice(5)]} ${mm.slice(0,4)}</div>`+
    `<div class="stat">${s.raw[i]} сообщ. · ${share}% моего месяца</div>`+msgs;
  card.style.display='block';
  const r = box.getBoundingClientRect();
  let tx = px - r.left + 18;
  if (tx + 340 > r.width) tx = px - r.left - 348;
  card.style.left = tx+'px';
  card.style.top = Math.max(4, py - r.top - card.offsetHeight - 14)+'px';
}

function moveCursor(i, slow){
  const cur = svg.querySelector('#cursorline');
  cur.style.transition = slow ? 'transform 1.35s linear' : 'none';
  cur.setAttribute('opacity', '0.4');
  cur.style.transform = `translateX(${X(i)}px)`;
}

svg.addEventListener('mousemove', ev=>{
  if (playTimer) return;
  const r = svg.getBoundingClientRect();
  const px = (ev.clientX-r.left)*W/r.width;
  if (px<ML||px>W-MR){ card.style.display='none'; return; }
  const i = Math.round((px-ML)/(W-ML-MR)*(N-1));
  moveCursor(i,false);
  let k = selected;
  if (k==null){
    const t = ev.target.closest('.stream');
    if (!t){ card.style.display='none'; return; }
    k = +t.dataset.k;
  }
  showCard(k,i,ev.clientX,ev.clientY,true);
});
svg.addEventListener('mouseleave', ()=>{ if(!playTimer){ card.style.display='none';
  const c=svg.querySelector('#cursorline'); if(c) c.setAttribute('opacity','0'); }});
svg.addEventListener('click', ()=>{ if(selected!=null) select(null); });

function select(k){
  stopPlay(); selected = k; draw(); renderLegend();
  if (k==null) statusEl.textContent='Ничего не выбрано — кликни на течение.';
  else {
    const s=AS[k], total=s.raw.reduce((a,b)=>a+b,0);
    const o=!s.extra && D.origins[s.k];
    statusEl.textContent = `${s.label}: ${total.toLocaleString('ru')} моих сообщений`+
      (o?` · исток ${D.months[o.m]}: «${o.text}»`:'');
  }
}

function renderLegend(){
  const lg=document.getElementById('legend'); lg.innerHTML='';
  AS.forEach((s,k)=>{
    const b=document.createElement('button');
    b.className='chip'+(selected===k?' active':'');
    b.innerHTML=`<span class="sw" style="background:${s.color}"></span>${s.label}`+(s.extra?' ✕':'');
    b.onclick=()=>{ if(s.extra && selected===k){ removeExtra(k); } else select(selected===k?null:k); };
    if (s.extra) b.title='повторный клик при выбранном — убрать из реки';
    lg.appendChild(b);
  });
  document.getElementById('tempbtn').className='chip tool'+(tempOn?' on':'');
  
  document.getElementById('playbtn').textContent = playTimer?'■ стоп':'▶ проплыть';
}

function removeExtra(k){
  const j = k - (D.series.length-1);
  added.splice(j,1); selected=null; G=recompute(); draw(); renderLegend();
}

document.getElementById('tempbtn').onclick=()=>{ tempOn=!tempOn; draw(); renderLegend(); };


const dl=document.getElementById('chatlist');
D.extra.forEach((s,ei)=>{ const o=document.createElement('option'); o.value=s.label; dl.appendChild(o); });
document.getElementById('chatpick').addEventListener('change', ev=>{
  const ei = D.extra.findIndex(s=>s.label===ev.target.value);
  if (ei<0 || added.includes(ei)) return;
  if (added.length>=4){ statusEl.textContent='Не больше четырёх дополнительных русел — сними какое-нибудь.'; return; }
  added.push(ei); ev.target.value='';
  G=recompute(); draw(); renderLegend();
  select(D.series.length-1+added.length-1);
});

function stopPlay(){ if(playTimer){ clearInterval(playTimer); playTimer=null;
  const b=document.getElementById('playbtn'); if(b) b.textContent='▶ проплыть'; }}
document.getElementById('playbtn').onclick=()=>{
  if (playTimer){ stopPlay(); return; }
  if (selected==null){ statusEl.textContent='Сначала выбери течение — потом поплывём.'; return; }
  const k=selected, idx=[];
  for (let i=0;i<N;i++) if (AS[k].raw[i]>0) idx.push(i);
  if (!idx.length) return;
  let j=0;
  document.getElementById('playbtn').textContent='■ стоп';
  const step=()=>{
    if (j>=idx.length){ stopPlay(); return; }
    const i=idx[j++];
    moveCursor(i,true);
    const r=svg.getBoundingClientRect();
    showCard(k,i, r.left+(X(i)/W)*r.width, r.top+r.height*0.32, false);
  };
  step();
  playTimer=setInterval(step, 1500);
};

document.getElementById('posterbtn').onclick=()=>{
  const body = svgBody(true);
  const title = selected!=null ? AS[selected].label+' · река общения' : 'Река общения';
  const full = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H+90}">`+
    `<rect width="${W}" height="${H+90}" fill="#0d0d0d"/>`+
    `<text x="24" y="40" font-family="system-ui,sans-serif" font-size="26" font-weight="700" fill="#fff">${title}</text>`+
    `<text x="24" y="62" font-family="system-ui,sans-serif" font-size="13" fill="#898781">1 112 331 сообщение · 2016–2026</text>`+
    `<g transform="translate(0,80)">${body.replace(/class="[^"]*"/g,'')}</g></svg>`;
  const img = new Image();
  img.onload = ()=>{
    const c = document.createElement('canvas');
    c.width = W*2; c.height = (H+90)*2;
    const ctx = c.getContext('2d');
    ctx.drawImage(img,0,0,c.width,c.height);
    const a = document.createElement('a');
    a.download = 'reka-obshcheniya.png';
    a.href = c.toDataURL('image/png');
    a.click();
  };
  img.src = 'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(full);
};

draw(); renderLegend();
</script></body></html>"""

OUT.mkdir(exist_ok=True)
n_years = int(months[-1][:4]) - int(months[0][:4]) + 1
NUM = {1: 'Один год', 2: 'Два года', 3: 'Три года', 4: 'Четыре года', 5: 'Пять лет',
       6: 'Шесть лет', 7: 'Семь лет', 8: 'Восемь лет', 9: 'Девять лет', 10: 'Десять лет',
       11: 'Одиннадцать лет', 12: 'Двенадцать лет'}
years_ru = NUM.get(n_years, f'{n_years} лет')
(OUT / 'river.html').write_text(page.replace('__DATA__', blob)
                                    .replace('__YEARS__', years_ru), encoding='utf-8')
print(f"записан out/river.html ({(OUT/'river.html').stat().st_size/1024:.0f} КБ); "
      f"доп. чатов в селекторе: {len(extra)}; событий: {len(events)}")
