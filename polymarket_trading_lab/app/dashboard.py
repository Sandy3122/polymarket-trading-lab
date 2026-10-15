"""Single-page paper-trading console served at ``/``."""

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Polymarket Trading Lab</title>
<style>
:root{--bg:#f4f6f9;--card:#fff;--card2:#f7f9fb;--line:#e1e6ec;--ink:#17202a;--mute:#687585;--green:#12a05c;--red:#d8412f;--blue:#2f6df6;--amber:#d99200;--shadow:0 1px 2px rgba(0,0,0,.04)}
[data-theme=dark]{--bg:#0d1117;--card:#151b23;--card2:#1b232d;--line:#263140;--ink:#e6edf3;--mute:#8b98a8;--green:#2ecc80;--red:#ff6b5b;--blue:#5b8cff;--amber:#f0b429;--shadow:none}
*{box-sizing:border-box}
body{font:14px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;background:var(--bg);color:var(--ink)}
.wrap{max-width:1400px;margin:0 auto;padding:16px 20px 40px}
.top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px}
.brand{display:flex;align-items:center;gap:10px}.logo{width:34px;height:34px;border-radius:9px;background:linear-gradient(135deg,var(--blue),var(--green));display:grid;place-items:center;color:#fff;font-weight:800}
h1{font-size:19px;margin:0}h2{font-size:14px;margin:0;font-weight:650}
.mute,small{color:var(--mute)}
.chips{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.chip{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:600;background:var(--card2);border:1px solid var(--line)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--mute)}.dot.ok{background:var(--green);box-shadow:0 0 0 3px rgba(46,204,128,.18)}.dot.bad{background:var(--red)}.dot.warn{background:var(--amber)}
.paper{color:var(--green)}
button{padding:7px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card2);color:var(--ink);cursor:pointer;font:inherit}
button:hover{border-color:var(--blue)}button:disabled{opacity:.5;cursor:not-allowed}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;box-shadow:var(--shadow)}
.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;gap:8px;flex-wrap:wrap}
.kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:12px}
@media(max-width:1100px){.kpis{grid-template-columns:repeat(3,1fr)}}@media(max-width:600px){.kpis{grid-template-columns:repeat(2,1fr)}}
.kpi small{font-size:12px}.kpi .v{font-size:21px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}.kpi .s{font-size:12px;margin-top:2px}
.pos{color:var(--green)}.neg{color:var(--red)}
.mkts{display:flex;gap:10px;overflow-x:auto;padding-bottom:6px;margin-bottom:12px}
.mk{min-width:210px;flex:1;cursor:pointer;border:1px solid var(--line);background:var(--card);border-radius:12px;padding:10px 12px}
.mk:hover{border-color:var(--blue)}.mk.sel{border-color:var(--blue);box-shadow:0 0 0 1px var(--blue)}
.mk .t{display:flex;justify-content:space-between;font-size:12px;color:var(--mute)}.mk b{font-size:19px;font-variant-numeric:tabular-nums}
.mk .win{color:var(--amber);font-weight:700}.mk .held{color:var(--blue);font-weight:700}
.main{display:grid;grid-template-columns:minmax(0,2fr) minmax(310px,1fr);gap:12px}
@media(max-width:1000px){.main{grid-template-columns:1fr}}
.quotes{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:8px 0}
.q{background:var(--card2);border-radius:8px;padding:7px 10px}.q small{font-size:11px}.q b{display:block;font-size:17px;font-variant-numeric:tabular-nums}
canvas{width:100%;display:block}#chart{height:330px}#eq{height:70px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.seg button{border:0;border-radius:0;background:transparent;padding:5px 11px;font-size:12px}.seg button.on{background:var(--blue);color:#fff}
.legend{display:flex;gap:14px;font-size:12px;color:var(--mute);margin-top:6px;flex-wrap:wrap}
.legend i{display:inline-block;width:16px;border-top:3px solid;vertical-align:middle;margin-right:5px}
input,select{font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card2);color:var(--ink);width:100%}
label{display:block;font-size:12px;color:var(--mute);margin:10px 0 4px}
.row{display:flex;gap:8px;align-items:center}.row>*{flex:1}.row .fit{flex:none}
.tok{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.tok button{padding:10px;font-weight:700;border-radius:8px}
.tok button.on[data-t=YES]{background:var(--green);color:#06210f;border-color:var(--green)}.tok button.on[data-t=NO]{background:var(--red);color:#2b0803;border-color:var(--red)}
.big{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0 4px}
.big button{padding:13px;font-size:15px;font-weight:800;border:0;color:#fff;letter-spacing:.3px}
.buy{background:var(--green);color:#06210f!important}.sell{background:var(--red);color:#2b0803!important}
.mini{padding:4px 9px;font-size:12px;border-radius:6px}
.est{font-size:12px;color:var(--mute);margin-top:6px}
hr{border:0;border-top:1px solid var(--line);margin:14px 0}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin-bottom:10px}
.tabs button{border:0;background:transparent;border-bottom:2px solid transparent;border-radius:0;color:var(--mute);padding:8px 12px}
.tabs button.on{color:var(--ink);border-bottom-color:var(--blue)}
table{width:100%;border-collapse:collapse}th,td{text-align:left;border-bottom:1px solid var(--line);padding:8px 6px;font-size:13px;font-variant-numeric:tabular-nums;white-space:nowrap}
th{color:var(--mute);font-weight:600;font-size:12px}.scroll{overflow-x:auto}
.tag{font-size:11px;padding:2px 7px;border-radius:999px;background:var(--card2);border:1px solid var(--line)}
.tag.stop_loss{color:var(--red);border-color:var(--red)}.tag.take_profit{color:var(--green);border-color:var(--green)}
.bar{position:relative;height:6px;border-radius:3px;background:linear-gradient(90deg,var(--red),var(--card2) 50%,var(--green));min-width:90px}
.bar i{position:absolute;top:-3px;width:3px;height:12px;background:var(--ink);border-radius:2px}
.sg{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:4px 14px}
.sg h3{grid-column:1/-1;margin:14px 0 0;font-size:13px;color:var(--blue)}
.sg label small{display:block;font-size:11px;margin-top:2px;opacity:.85}.ap{font-size:10px;color:var(--amber)}
.empty{padding:22px;text-align:center;color:var(--mute)}
.help{background:var(--card2);border:1px dashed var(--line);border-radius:10px;padding:10px 12px;font-size:13px;color:var(--mute);margin-bottom:12px}
#toasts{position:fixed;right:16px;bottom:16px;display:flex;flex-direction:column;gap:8px;z-index:9}
.toast{padding:10px 14px;border-radius:10px;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--green);box-shadow:0 6px 20px rgba(0,0,0,.3);max-width:360px}
.toast.err{border-left-color:var(--red)}
</style></head><body><div class="wrap">

<div class="top">
  <div class="brand"><div class="logo">P</div><div><h1>Polymarket Trading Lab</h1><small><span class="paper">PAPER ONLY</span> · live trading disabled</small></div></div>
  <div class="chips">
    <span class="chip"><span class="dot" id="dWorker"></span><span id="tWorker">worker …</span></span>
    <span class="chip"><span class="dot" id="dFeed"></span><span id="tFeed">feed …</span></span>
    <span class="chip" id="clock"></span>
    <button id="btnStart">▶ Start worker</button><button id="btnStop">■ Stop</button>
    <button id="btnSettings">⚙ Settings</button><button id="btnTheme" title="Toggle theme">◐</button>
  </div>
</div>

<div class="help" id="help" style="display:none"></div>

<div class="kpis" id="kpis"></div>

<div class="mkts" id="mkts"></div>

<div class="main">
  <div class="card">
    <div class="head"><div><h2 id="mTitle">Select a market</h2><small id="mMeta"></small></div>
      <div class="chips"><div class="seg" id="rangeSeg"><button data-r="60">1m</button><button data-r="300">5m</button><button data-r="0" class="on">All</button></div></div></div>
    <div class="quotes" id="quotes"></div>
    <canvas id="chart"></canvas>
    <div class="legend">
      <span><i style="border-color:#2ecc80"></i>YES bid</span><span><i style="border-color:#ff6b5b"></i>NO bid</span>
      <span><i style="border-color:#8b98a8;border-top-style:dashed"></i>Entry</span>
      <span><i style="border-color:#ff6b5b;border-top-style:dashed"></i>Stop loss</span>
      <span><i style="border-color:#2ecc80;border-top-style:dashed"></i>Take profit</span>
    </div>
  </div>

  <div class="card">
    <div class="head"><h2>Trade ticket</h2><small>paper money</small></div>
    <div class="tok" id="tokSeg"><button data-t="YES" class="on">YES</button><button data-t="NO">NO</button></div>
    <label>Shares</label>
    <div class="row"><input id="qty" type="number" min="1" step="1" value="10">
      <span class="fit"><button class="mini" data-q="10">10</button> <button class="mini" data-q="25">25</button> <button class="mini" data-q="50">50</button> <button class="mini" data-q="100">100</button> <button class="mini" data-q="max">Max</button></span></div>
    <div class="est" id="estimate"></div>
    <div class="big"><button class="buy" id="btnBuy">BUY</button><button class="sell" id="btnSell">SELL</button></div>
    <hr>
    <div class="head"><h2>Stop loss &amp; take profit</h2></div>
    <small id="exitHint">Buy shares first, then protect them here.</small>
    <div class="row"><div><label>Stop loss (bid ≤)</label><input id="sl" type="number" step="0.01" min="0.01" max="0.99" placeholder="0.90"></div>
      <div><label>Take profit (bid ≥)</label><input id="tp" type="number" step="0.01" min="0.01" max="0.99" placeholder="0.99"></div></div>
    <div class="row" style="margin-top:8px;flex-wrap:wrap"><small class="fit">Presets:</small>
      <button class="mini" data-sl="-0.03">SL −3¢</button><button class="mini" data-sl="-0.05">SL −5¢</button><button class="mini" data-sl="-0.10">SL −10¢</button>
      <button class="mini" data-tp="0.03">TP +3¢</button><button class="mini" data-tp="0.05">TP +5¢</button></div>
    <div class="row" style="margin-top:10px"><button id="btnSetExit">Save levels</button><button id="btnClearExit">Clear</button></div>
  </div>
</div>

<div class="card" style="margin-top:12px">
  <div class="head"><h2>Open positions</h2><small id="posSum"></small></div>
  <div class="scroll" id="positions"></div>
</div>

<div class="main" style="margin-top:12px">
  <div class="card">
    <div class="tabs" id="tabs"><button data-tab="orders" class="on">Orders &amp; fills</button><button data-tab="decisions">Strategy decisions</button><button data-tab="replays">Replays</button><button data-tab="settings">⚙ Settings</button></div>
    <div class="scroll" id="tab-orders"></div><div class="scroll" id="tab-decisions" style="display:none"></div><div class="scroll" id="tab-replays" style="display:none"></div><div id="tab-settings" style="display:none"></div>
  </div>
  <div class="card"><div class="head"><h2>Equity curve</h2><small>this browser session</small></div><canvas id="eq"></canvas><div id="eqNote" class="est"></div></div>
</div>
</div><div id="toasts"></div>

<script>
const $=s=>document.querySelector(s);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=v=>v==null||v===''?null:Number(v);
const f=(v,d=4)=>v==null?'—':Number(v).toFixed(d);
const money=v=>v==null?'—':(Number(v)<0?'-':'')+'$'+Math.abs(Number(v)).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const cls=v=>Number(v)>0?'pos':Number(v)<0?'neg':'';
const signed=v=>(Number(v)>0?'+':'')+money(v);
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
let S={market:null,token:'YES',portfolio:null,live:[],ticks:null,range:0,hover:null,eq:JSON.parse(localStorage.getItem('eq')||'[]'),stats:null};

async function api(path,opts){
  const r=await fetch(path,opts);let b=null;try{b=await r.json()}catch(e){}
  if(!r.ok)throw new Error((b&&b.detail)||('HTTP '+r.status));return b}
const post=(p,body,m='POST')=>api(p,{method:m,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
function toast(msg,ok=true){const d=document.createElement('div');d.className='toast'+(ok?'':' err');d.textContent=msg;$('#toasts').appendChild(d);setTimeout(()=>d.remove(),4200)}

/* theme */
const savedTheme=localStorage.getItem('theme');if(savedTheme)document.documentElement.dataset.theme=savedTheme;
$('#btnTheme').onclick=()=>{const t=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=t;localStorage.setItem('theme',t);draw();drawEq()};

/* ---------- overview ---------- */
function sparkSvg(a,w=90,h=24){if(!a||a.length<2)return '';const lo=Math.min(...a),hi=Math.max(...a),r=(hi-lo)||1;
  const pts=a.map((v,i)=>`${(i/(a.length-1)*w).toFixed(1)},${(h-(v-lo)/r*(h-2)-1).toFixed(1)}`).join(' ');
  const up=a[a.length-1]>=a[0];return `<svg width="${w}" height="${h}"><polyline fill="none" stroke="${up?css('--green'):css('--red')}" stroke-width="1.6" points="${pts}"/></svg>`}

async function loadOverview(){
  const x=await api('/ops/overview');const p=x.portfolio;S.portfolio=p;S.stats=x.stats;
  const w=x.worker;$('#tWorker').textContent='worker '+w.status;$('#dWorker').className='dot '+(w.status==='running'?'ok':w.status==='stopped'?'':'bad');
  const eq=Number(p.equity),init=10000;
  if(!S.eq.length||Date.now()-S.eq[S.eq.length-1].t>4000){S.eq.push({t:Date.now(),v:eq});S.eq=S.eq.slice(-400);localStorage.setItem('eq',JSON.stringify(S.eq))}
  const pct=(Number(p.total_pnl)/init*100);
  $('#kpis').innerHTML=[['Equity',money(p.equity),'',`cash + positions`],['Cash',money(p.cash),'',`${money(p.market_value)} in positions`],
   ['Realized P&L',signed(p.realized_pnl),cls(p.realized_pnl),'closed trades'],['Unrealized P&L',signed(p.unrealized_pnl),cls(p.unrealized_pnl),'open, at bid'],
   ['Total P&L',signed(p.total_pnl),cls(p.total_pnl),(pct>=0?'+':'')+pct.toFixed(2)+'% of start'],['Open orders',x.stats.open_orders,'',`${x.stats.fills} filled · ${x.stats.decisions} decisions`]]
   .map(a=>`<div class="card kpi"><small>${a[0]}</small><div class="v ${a[2]}">${esc(a[1])}</div><div class="s mute">${esc(a[3])}</div></div>`).join('');
  renderPositions(p.positions);renderDecisions(x.decisions);renderReplays(x.replays);drawEq();
  const help=$('#help');
  if(w.status!=='running'){help.style.display='block';help.innerHTML='<b>Worker is stopped.</b> Press <b>▶ Start worker</b> to stream live prices. Nothing trades or updates until it runs.'}
  else if(!S.live.length){help.style.display='block';help.innerHTML='<b>Waiting for live markets…</b> The worker is running; prices appear within a few seconds. If this stays empty, no 10–20 min crypto market is currently open.'}
  else help.style.display='none';
}

function renderPositions(list){
  $('#posSum').textContent=list.length?`${list.length} open · ${signed(list.reduce((a,p)=>a+Number(p.unrealized_pnl),0))} unrealized`:'';
  if(!list.length){$('#positions').innerHTML='<div class="empty">No open positions yet. Use BUY in the ticket, or wait for the M1 strategy to get filled.</div>';return}
  $('#positions').innerHTML='<table><tr><th>Market</th><th>Side</th><th>Shares</th><th>Entry</th><th>Mark</th><th>Value</th><th>P&amp;L</th><th>P&amp;L %</th><th>Stop → Target</th><th></th></tr>'+list.map(p=>{
   const e=+p.average_entry_price,m=p.mark_price==null?null:+p.mark_price,sl=num(p.stop_loss_price),tp=num(p.take_profit_price);
   const lo=Math.min(sl??e-.05,e-.02),hi=Math.max(tp??e+.05,e+.02);const at=m==null?50:Math.max(0,Math.min(100,(m-lo)/(hi-lo)*100));
   const pc=m==null?0:(m-e)/e*100;
   return `<tr><td>${esc((p.question||'').slice(0,46))}</td><td><b class="${p.token==='YES'?'pos':'neg'}">${esc(p.token)}</b></td><td>${f(p.quantity,2)}</td><td>${f(e)}</td><td>${f(m)}</td><td>${money(p.market_value)}</td>
   <td class="${cls(p.unrealized_pnl)}">${signed(p.unrealized_pnl)}</td><td class="${cls(pc)}">${pc>=0?'+':''}${pc.toFixed(1)}%</td>
   <td><div class="mute" style="font-size:11px">${f(sl,2)} → ${f(tp,2)} ${p.exit_status&&p.exit_status!=='active'?`<span class="tag ${esc(p.exit_status)}">${esc(p.exit_status.replace('_',' '))}</span>`:''}</div><div class="bar"><i style="left:${at}%"></i></div></td>
   <td><button class="mini" data-sel="${p.market_id}|${esc(p.token)}">Open</button> <button class="mini" data-close="${p.market_id}|${esc(p.token)}|${esc(p.quantity)}">Close</button></td></tr>`}).join('')+'</table>'}
$('#positions').addEventListener('click',async e=>{
  const sel=e.target.dataset.sel,cl=e.target.dataset.close;
  if(sel){const [m,t]=sel.split('|');S.market=m;setToken(t);await refresh()}
  if(cl){const [m,t,q]=cl.split('|');try{const r=await post('/paper/trade',{market_id:+m,token:t,side:'SELL',quantity:q});toast(`Closed ${f(r.quantity,2)} ${t} @ ${f(r.price)}`)}catch(err){toast(err.message,false)}refresh()}});

function renderDecisions(list){const seen=[],rows=[];
  for(const d of list){const k=d.market_id+'|'+d.reason+'|'+d.intents;if(seen[seen.length-1]===k)continue;seen.push(k);rows.push(d)}
  $('#tab-decisions').innerHTML='<table><tr><th>Time (UTC)</th><th>Market</th><th>Reason</th><th>Intent</th></tr>'+rows.slice(0,15).map(d=>`<tr><td>${esc(d.decision_time.slice(11,19))}</td><td>${esc(d.market_id)}</td><td>${esc(d.reason)}</td><td>${esc(sum(d.intents))}</td></tr>`).join('')+'</table>'}
function sum(s){try{return JSON.parse(s).map(i=>`${i.side} ${i.token} ${i.quantity}@${i.price}`).join(', ')||'—'}catch(e){return s}}
function renderReplays(list){$('#tab-replays').innerHTML=list.length?'<table><tr><th>Started</th><th>Name</th><th>Status</th><th>Events</th><th>Net P&amp;L</th></tr>'+list.map(d=>`<tr><td>${esc(d.started_at)}</td><td>${esc(d.name)}</td><td>${esc(d.status)}</td><td>${esc(d.event_count)}</td><td>${esc(d.net_pnl)}</td></tr>`).join('')+'</table>':'<div class="empty">No replay runs yet.</div>'}
async function loadOrders(){
  const o=(await api('/orders?limit=80')).filter(o=>o.status!=='cancelled');
  $('#tab-orders').innerHTML=o.length?'<table><tr><th>Time (UTC)</th><th>Market</th><th>Side</th><th>Token</th><th>Limit</th><th>Filled</th><th>Avg fill</th><th>Status</th></tr>'+o.slice(0,25).map(r=>`<tr><td>${esc((r.created_at||'').slice(11,19))}</td><td>${esc((r.question||'').slice(0,44))}</td><td><b class="${r.side==='BUY'?'pos':'neg'}">${esc(r.side)}</b></td><td>${esc(r.token)}</td><td>${f(r.price)}</td><td>${f(r.filled_quantity,2)}/${f(r.quantity,2)}</td><td>${f(r.average_fill_price)}</td><td>${esc(r.status)}${r.reject_reason?' — '+esc(r.reject_reason):''}</td></tr>`).join('')+'</table>':'<div class="empty">No orders yet.</div>'}
$('#tabs').addEventListener('click',e=>{const t=e.target.dataset.tab;if(!t)return;document.querySelectorAll('#tabs button').forEach(b=>b.classList.toggle('on',b.dataset.tab===t));if(t==='settings')loadSettings();for(const n of ['orders','decisions','replays','settings'])$('#tab-'+n).style.display=n===t?'':'none'});

/* ---------- live markets ---------- */
const asset=q=>(q.match(/^(.*?) (Up or Down|above|below)/i)||[,q.slice(0,18)])[1];
async function loadLive(){
  S.live=await api('/live/markets');
  if(S.live.length&&(!S.market||!S.live.some(m=>String(m.id)===String(S.market))))S.market=S.live[0].id;
  renderMarkets();const fresh=S.live.length?Math.min(...S.live.map(m=>(Date.now()-Date.parse(m.quote.observed_at))/1000)):null;
  $('#tFeed').textContent=fresh==null?'feed: none':`feed ${S.live.length} mkts · ${fresh.toFixed(0)}s ago`;$('#dFeed').className='dot '+(fresh==null?'':fresh<15?'ok':fresh<60?'warn':'bad')}
function renderMarkets(){
  const held=new Set((S.portfolio?.positions||[]).map(p=>String(p.market_id)));
  $('#mkts').innerHTML=S.live.length?S.live.map(m=>{const left=Math.floor((Date.parse(m.end_time)-Date.now())/1000);const win=left>0&&left<=120;
   return `<div class="mk ${String(m.id)===String(S.market)?'sel':''}" data-m="${m.id}"><div class="t"><span>${esc(asset(m.question))}</span><span class="${win?'win':''}" data-end="${esc(m.end_time)}">${cd(left)}${win?' · M1 window':''}</span></div>
   <div class="row" style="justify-content:space-between"><div><b class="pos">${f(m.quote.yes_bid,2)}</b> <small>YES</small> ${held.has(String(m.id))?'<span class="held">● held</span>':''}</div>${sparkSvg(m.spark)}</div>
   <div class="t"><span>NO ${f(m.quote.no_bid,2)}</span><span>spread ${m.quote.yes_ask&&m.quote.yes_bid?((m.quote.yes_ask-m.quote.yes_bid)*100).toFixed(0)+'¢':'—'}</span></div></div>`}).join(''):'<div class="card empty" style="width:100%">No live markets yet.</div>'}
const cd=s=>s<=0?'ended':Math.floor(s/60)+':'+String(s%60).padStart(2,'0');
$('#mkts').addEventListener('click',e=>{const el=e.target.closest('.mk');if(!el)return;S.market=el.dataset.m;S.hover=null;renderMarkets();loadTicks()});
setInterval(()=>{document.querySelectorAll('[data-end]').forEach(el=>{const left=Math.floor((Date.parse(el.dataset.end)-Date.now())/1000);el.textContent=cd(left)+(left>0&&left<=120?' · M1 window':'')});$('#clock').textContent=new Date().toISOString().slice(11,19)+' UTC'},1000);

async function loadTicks(){
  if(!S.market)return;try{S.ticks=await api(`/live/markets/${S.market}/ticks`)}catch(e){return}
  const t=S.ticks,q=t.quote;$('#mTitle').textContent=t.question;$('#mMeta').textContent=`ends ${t.end_time.slice(11,19)} UTC · ${t.ticks.length} ticks`;
  $('#quotes').innerHTML=q?[['YES bid',q.yes_bid,'pos'],['YES ask',q.yes_ask,'pos'],['NO bid',q.no_bid,'neg'],['NO ask',q.no_ask,'neg']].map(a=>`<div class="q"><small>${a[0]}</small><b class="${a[2]}">${f(a[1])}</b></div>`).join(''):'';
  updateTicket();draw()}

/* ---------- main chart ---------- */
function draw(){
  const cv=$('#chart'),dpr=devicePixelRatio||1,W=cv.clientWidth,H=cv.clientHeight;cv.width=W*dpr;cv.height=H*dpr;const c=cv.getContext('2d');c.scale(dpr,dpr);c.clearRect(0,0,W,H);
  let ticks=(S.ticks?.ticks||[]).map(k=>({t:Date.parse(k.t),y:num(k.yes),n:num(k.no)}));
  if(S.range&&ticks.length){const cut=ticks[ticks.length-1].t-S.range*1000;ticks=ticks.filter(k=>k.t>=cut)}
  const L=44,R=54,T=10,B=22,mute=css('--mute'),line=css('--line'),G=css('--green'),Rd=css('--red');c.font='11px system-ui';c.fillStyle=mute;
  if(ticks.length<2){c.fillText('Waiting for live ticks… (start the worker)',L+10,H/2);return}
  const pos=(S.portfolio?.positions||[]).filter(p=>String(p.market_id)===String(S.market));const lv=[];
  pos.forEach(p=>[['entry',p.average_entry_price],['sl',p.stop_loss_price],['tp',p.take_profit_price]].forEach(([k,v])=>{if(v!=null)lv.push({k,v:+v,tok:p.token})}));
  const vals=ticks.flatMap(k=>[k.y,k.n]).filter(v=>v!=null).concat(lv.map(l=>l.v));let lo=Math.min(...vals),hi=Math.max(...vals);const pad=Math.max(.02,(hi-lo)*.15);lo=Math.max(0,lo-pad);hi=Math.min(1,hi+pad);
  const t0=ticks[0].t,t1=ticks[ticks.length-1].t;const X=t=>L+(t-t0)/Math.max(1,t1-t0)*(W-L-R),Y=v=>T+(1-(v-lo)/(hi-lo))*(H-T-B);
  c.strokeStyle=line;c.lineWidth=1;for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4,y=Y(v);c.beginPath();c.moveTo(L,y);c.lineTo(W-R,y);c.stroke();c.fillText(v.toFixed(2),6,y+4)}
  for(let i=0;i<=4;i++){const t=t0+(t1-t0)*i/4;c.fillText(new Date(t).toISOString().slice(14,19),X(t)-14,H-6)}
  const path=(key,color,fill)=>{c.beginPath();let on=false,fx=null,lx=null;for(const k of ticks){if(k[key]==null)continue;const x=X(k.t),y=Y(k[key]);on?c.lineTo(x,y):c.moveTo(x,y);if(fx==null)fx=x;lx=x;on=true}
    c.strokeStyle=color;c.lineWidth=2;c.stroke();if(fill&&fx!=null){c.lineTo(lx,H-B);c.lineTo(fx,H-B);c.closePath();const g=c.createLinearGradient(0,T,0,H-B);g.addColorStop(0,color+'40');g.addColorStop(1,color+'00');c.fillStyle=g;c.fill()}};
  path('y',G,true);path('n',Rd,false);
  c.setLineDash([6,4]);c.lineWidth=1.5;for(const l of lv){const col=l.k==='sl'?Rd:l.k==='tp'?G:mute;c.strokeStyle=col;const y=Y(l.v);c.beginPath();c.moveTo(L,y);c.lineTo(W-R,y);c.stroke();c.fillStyle=col;c.fillText(`${l.k.toUpperCase()} ${l.tok} ${l.v.toFixed(2)}`,L+6,y-4)}c.setLineDash([]);
  const last=ticks[ticks.length-1];for(const [k,col] of [['y',G],['n',Rd]]){if(last[k]==null)continue;const y=Y(last[k]);c.fillStyle=col;c.fillRect(W-R+2,y-8,48,16);c.fillStyle='#fff';c.fillText(last[k].toFixed(2),W-R+8,y+4)}
  if(S.hover!=null){const hx=Math.max(L,Math.min(W-R,S.hover));const tt=t0+(hx-L)/(W-L-R)*(t1-t0);let b=ticks[0];for(const k of ticks)if(Math.abs(k.t-tt)<Math.abs(b.t-tt))b=k;
    c.strokeStyle=mute;c.lineWidth=1;c.beginPath();c.moveTo(X(b.t),T);c.lineTo(X(b.t),H-B);c.stroke();
    const txt=`${new Date(b.t).toISOString().slice(11,19)}  YES ${f(b.y,2)}  NO ${f(b.n,2)}`;const tw=c.measureText(txt).width+14,bx=Math.min(X(b.t)+8,W-R-tw);c.fillStyle=css('--card2');c.fillRect(bx,T+4,tw,20);c.strokeStyle=line;c.strokeRect(bx,T+4,tw,20);c.fillStyle=css('--ink');c.fillText(txt,bx+7,T+18)}
}
$('#chart').addEventListener('mousemove',e=>{S.hover=e.offsetX;draw()});$('#chart').addEventListener('mouseleave',()=>{S.hover=null;draw()});
$('#rangeSeg').addEventListener('click',e=>{if(e.target.dataset.r==null)return;S.range=+e.target.dataset.r;document.querySelectorAll('#rangeSeg button').forEach(b=>b.classList.toggle('on',b===e.target));draw()});
addEventListener('resize',()=>{draw();drawEq()});

function drawEq(){
  const cv=$('#eq'),dpr=devicePixelRatio||1,W=cv.clientWidth,H=cv.clientHeight;cv.width=W*dpr;cv.height=H*dpr;const c=cv.getContext('2d');c.scale(dpr,dpr);c.clearRect(0,0,W,H);
  const a=S.eq;if(a.length<2){$('#eqNote').textContent='Collecting data…';return}
  const lo=Math.min(...a.map(p=>p.v)),hi=Math.max(...a.map(p=>p.v)),r=(hi-lo)||1,up=a[a.length-1].v>=a[0].v,col=up?css('--green'):css('--red');
  c.beginPath();a.forEach((p,i)=>{const x=i/(a.length-1)*W,y=H-6-(p.v-lo)/r*(H-12);i?c.lineTo(x,y):c.moveTo(x,y)});c.strokeStyle=col;c.lineWidth=2;c.stroke();
  $('#eqNote').innerHTML=`low ${money(lo)} · high ${money(hi)} · change <span class="${cls(a[a.length-1].v-a[0].v)}">${signed(a[a.length-1].v-a[0].v)}</span>`}

/* ---------- settings ---------- */
let SET=[];
async function loadSettings(){const r=await api('/settings');SET=r.fields;let g='',h=`<div class="help">Data source: <b>${esc(r.data_source)}</b>. Paper trading only — no broker keys are used or stored. Changes save to the database and apply as noted.</div><div class="sg">`;
  for(const f of SET){if(f.group!==g){g=f.group;h+=`<h3>${esc(g)}</h3>`}
   const inp=f.type==='bool'?`<input type="checkbox" data-k="${f.key}" ${f.value==='true'?'checked':''} style="width:auto">`:f.choices?`<select data-k="${f.key}">${f.choices.map(c=>`<option ${c===f.value?'selected':''}>${c}</option>`).join('')}</select>`:`<input data-k="${f.key}" value="${esc(f.value)}" ${f.type==='number'?'type="number" step="any"':''}>`;
   h+=`<div><label>${esc(f.label)} <span class="ap">· applies: ${esc(f.applies)}</span>${inp.startsWith('<input type="checkbox')?'':''}</label>${inp}<small class="mute">${esc(f.help)}${f.value!==f.default?' · default '+esc(f.default):''}</small></div>`}
  h+='</div><div class="row" style="margin-top:14px;max-width:360px"><button id="btnSaveSet" class="buy" style="padding:10px;color:#06210f">Save settings</button><button id="btnResetSet">Reset to defaults</button></div>';
  $('#tab-settings').innerHTML=h;
  $('#btnSaveSet').onclick=async()=>{const body={};document.querySelectorAll('#tab-settings [data-k]').forEach(el=>{const k=el.dataset.k,v=el.type==='checkbox'?String(el.checked):el.value,old=SET.find(f=>f.key===k).value;if(v!==old)body[k]=v});
    if(!Object.keys(body).length)return toast('Nothing changed');try{await api('/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});toast('Settings saved');loadSettings()}catch(e){toast(e.message,false)}};
  $('#btnResetSet').onclick=async()=>{if(!confirm('Reset all editable settings to defaults?'))return;await api('/settings/reset',{method:'POST'});toast('Defaults restored');loadSettings()}}
$('#btnSettings').onclick=()=>{document.querySelector('#tabs [data-tab=settings]').click();$('#tabs').scrollIntoView({behavior:'smooth'})};

/* ---------- ticket ---------- */
function setToken(t){S.token=t;document.querySelectorAll('#tokSeg button').forEach(b=>b.classList.toggle('on',b.dataset.t===t));updateTicket()}
$('#tokSeg').addEventListener('click',e=>{if(e.target.dataset.t)setToken(e.target.dataset.t)});
$('#qty').addEventListener('input',updateTicket);
document.addEventListener('click',e=>{const q=e.target.dataset.q;if(q){const qt=S.ticks?.quote;if(q==='max'&&qt&&S.portfolio){const ask=num(S.token==='YES'?qt.yes_ask:qt.no_ask);if(ask)$('#qty').value=Math.floor(Math.min(250/ask,Number(S.portfolio.cash)/ask))}else if(q!=='max')$('#qty').value=q;updateTicket()}
  const p=currentPosition();if(e.target.dataset.sl&&p){$('#sl').value=(+p.average_entry_price+ +e.target.dataset.sl).toFixed(2)}if(e.target.dataset.tp&&p){$('#tp').value=(+p.average_entry_price+ +e.target.dataset.tp).toFixed(2)}});
const currentPosition=()=>(S.portfolio?.positions||[]).find(p=>String(p.market_id)===String(S.market)&&p.token===S.token);
function updateTicket(){
  const q=S.ticks?.quote,qty=num($('#qty').value)||0;if(!q)return;const ask=num(S.token==='YES'?q.yes_ask:q.no_ask),bid=num(S.token==='YES'?q.yes_bid:q.no_bid);
  $('#estimate').innerHTML=`BUY ≈ <b>${money(ask*qty)}</b> at ask ${f(ask)} · SELL ≈ <b>${money(bid*qty)}</b> at bid ${f(bid)}<br>Max win if ${S.token} resolves true: <span class="pos">${signed((1-ask)*qty)}</span> · max loss: <span class="neg">${signed(-ask*qty)}</span>`;
  const p=currentPosition();$('#exitHint').textContent=p?`Holding ${f(p.quantity,2)} ${p.token} @ ${f(p.average_entry_price)}. Exits trigger on the ${p.token} bid.`:'Buy shares first, then protect them here.';
  const key=p?p.market_id+p.token:'';for(const [id,v] of [['#sl',p?.stop_loss_price],['#tp',p?.take_profit_price]]){const el=$(id);if(document.activeElement!==el&&el.dataset.pos!==key)el.value=v!=null?Number(v).toFixed(2):''}$('#sl').dataset.pos=$('#tp').dataset.pos=key}
async function trade(side){try{const r=await post('/paper/trade',{market_id:+S.market,token:S.token,side,quantity:$('#qty').value});toast(`${side} filled: ${f(r.quantity,2)} ${r.token} @ ${f(r.price)}`)}catch(e){toast(e.message,false)}refresh()}
$('#btnBuy').onclick=()=>trade('BUY');$('#btnSell').onclick=()=>trade('SELL');
$('#btnSetExit').onclick=async()=>{try{await post('/paper/exits',{market_id:+S.market,token:S.token,stop_loss_price:$('#sl').value||null,take_profit_price:$('#tp').value||null},'PUT');toast('Levels saved — worker will close the position when hit')}catch(e){toast(e.message,false)}refresh()};
$('#btnClearExit').onclick=async()=>{try{await api(`/paper/exits/${S.market}/${S.token}`,{method:'DELETE'});$('#sl').value=$('#tp').value='';toast('Levels cleared')}catch(e){toast(e.message,false)}refresh()};
async function worker(a){try{await api('/ops/worker/'+a,{method:'POST'});toast('Worker '+(a==='start'?'started':'stopped'))}catch(e){toast(e.message,false)}refresh()}
$('#btnStart').onclick=()=>worker('start');$('#btnStop').onclick=()=>worker('stop');

async function refresh(){try{await loadLive();await loadOverview();await loadTicks();await loadOrders()}catch(e){console.error(e)}}
refresh();setInterval(()=>{loadTicks().catch(()=>{})},1500);setInterval(refresh,5000);
</script></body></html>
"""
