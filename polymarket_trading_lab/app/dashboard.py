"""Single-page paper-trading console served at ``/``."""

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Polymarket Trading Lab</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--line:#e3e7ec;--ink:#17202a;--mute:#64707d;--green:#12804a;--red:#c0392b;--blue:#2563eb}
*{box-sizing:border-box}
body{font:14px system-ui,-apple-system,sans-serif;margin:0;background:var(--bg);color:var(--ink)}
.wrap{max-width:1320px;margin:0 auto;padding:20px}
header{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
h1{font-size:22px;margin:0}h2{font-size:15px;margin:0 0 12px}
small,.mute{color:var(--mute)}
.badge{background:#dff7e8;color:#176b38;padding:5px 10px;border-radius:999px;font-weight:700;font-size:12px}
.pill{padding:3px 9px;border-radius:999px;font-size:12px;font-weight:600;background:#eef1f4}
.pill.running{background:#dff7e8;color:#176b38}.pill.error,.pill.stale{background:#ffe9e6;color:#9d251b}
button{padding:7px 12px;border:1px solid #ccd4dc;border-radius:6px;background:#fff;cursor:pointer;font:inherit}
button:hover{background:#f1f4f7}button:disabled{opacity:.5;cursor:not-allowed}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:16px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.kpi .v{font-size:22px;font-weight:700;margin-top:4px;font-variant-numeric:tabular-nums}
.pos{color:var(--green)}.neg{color:var(--red)}
.main{display:grid;grid-template-columns:minmax(0,2fr) minmax(300px,1fr);gap:12px}
@media(max-width:960px){.main{grid-template-columns:1fr}}
select,input{font:inherit;padding:7px 9px;border:1px solid #ccd4dc;border-radius:6px;background:#fff;width:100%}
.row{display:flex;gap:8px;align-items:center}.row>*{flex:1}
.quotes{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0}
.q{border:1px solid var(--line);border-radius:8px;padding:8px 10px}.q b{display:block;font-size:18px;font-variant-numeric:tabular-nums}
canvas{width:100%;height:340px;display:block}
.legend{display:flex;gap:14px;font-size:12px;color:var(--mute);margin-top:6px;flex-wrap:wrap}
.legend i{display:inline-block;width:18px;height:0;border-top:3px solid;vertical-align:middle;margin-right:5px}
.seg{display:flex;border:1px solid #ccd4dc;border-radius:6px;overflow:hidden}
.seg button{flex:1;border:0;border-radius:0}.seg button.on{background:var(--ink);color:#fff}
.big{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0}
.big button{padding:12px;font-size:15px;font-weight:700;color:#fff;border:0}
.buy{background:var(--green)}.buy:hover{background:#0e6a3d}.sell{background:var(--red)}.sell:hover{background:#a52e22}
label{display:block;font-size:12px;color:var(--mute);margin:10px 0 4px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;border-bottom:1px solid #edf0f2;padding:7px 6px;font-size:13px;font-variant-numeric:tabular-nums}
th{color:var(--mute);font-weight:600}
.scroll{overflow-x:auto}
.msg{min-height:18px;font-size:12px;margin-top:6px}
section{margin-top:12px}
.tag{font-size:11px;padding:2px 6px;border-radius:4px;background:#eef1f4}
.tag.stop_loss{background:#ffe9e6;color:#9d251b}.tag.take_profit{background:#dff7e8;color:#176b38}
</style></head><body><div class="wrap">
<header>
  <div><h1>Polymarket Trading Lab</h1><small>Local paper operations console · prices update live while the worker runs</small></div>
  <div class="row" style="flex:none"><span class="badge">PAPER ONLY · LIVE DISABLED</span>
    <span id="workerPill" class="pill">worker …</span>
    <button id="btnStart">Start worker</button><button id="btnStop">Stop worker</button></div>
</header>

<div class="kpis" id="kpis"></div>

<div class="main">
  <div class="card">
    <div class="row" style="margin-bottom:8px"><select id="marketSel"></select></div>
    <small id="marketMeta"></small>
    <div class="quotes" id="quotes"></div>
    <canvas id="chart"></canvas>
    <div class="legend">
      <span><i style="border-color:#12804a"></i>YES bid</span><span><i style="border-color:#c0392b"></i>NO bid</span>
      <span><i style="border-color:#64707d;border-top-style:dashed"></i>Entry</span>
      <span><i style="border-color:#c0392b;border-top-style:dashed"></i>Stop loss</span>
      <span><i style="border-color:#12804a;border-top-style:dashed"></i>Take profit</span>
    </div>
  </div>

  <div class="card">
    <h2>Trade ticket <small>(paper)</small></h2>
    <div class="seg" id="tokSeg"><button data-t="YES" class="on">YES</button><button data-t="NO">NO</button></div>
    <label>Shares</label><input id="qty" type="number" min="1" step="1" value="10">
    <div class="mute" id="estimate" style="margin-top:6px"></div>
    <div class="big"><button class="buy" id="btnBuy">BUY</button><button class="sell" id="btnSell">SELL</button></div>
    <div class="msg" id="tradeMsg"></div>
    <hr style="border:0;border-top:1px solid var(--line);margin:14px 0">
    <h2>Stop loss &amp; take profit</h2>
    <small id="exitHint">Select a market where you hold shares.</small>
    <div class="row"><div><label>Stop loss (bid ≤)</label><input id="sl" type="number" step="0.01" min="0.01" max="0.99" placeholder="e.g. 0.90"></div>
      <div><label>Take profit (bid ≥)</label><input id="tp" type="number" step="0.01" min="0.01" max="0.99" placeholder="e.g. 0.99"></div></div>
    <div class="row" style="margin-top:10px"><button id="btnSetExit">Save levels</button><button id="btnClearExit">Clear</button></div>
    <div class="msg" id="exitMsg"></div>
  </div>
</div>

<section class="card"><h2>Open positions</h2><div class="scroll" id="positions"></div></section>
<section class="card"><h2>Recent orders &amp; fills</h2><div class="scroll" id="orders"></div></section>
<section class="card"><h2>Strategy decisions <small>(M1 auto-strategy, identical repeats collapsed)</small></h2><div class="scroll" id="decisions"></div></section>
<section class="card"><h2>Replay runs</h2><div class="scroll" id="replays"></div></section>
</div>
<script>
const $=s=>document.querySelector(s);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=v=>v==null?null:Number(v);
const f=(v,d=4)=>v==null?'—':Number(v).toFixed(d);
const money=v=>v==null?'—':(Number(v)<0?'-':'')+'$'+Math.abs(Number(v)).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const cls=v=>Number(v)>0?'pos':Number(v)<0?'neg':'';
const signed=v=>(Number(v)>0?'+':'')+money(v);
let state={market:null,token:'YES',portfolio:null,live:[],ticks:null};

async function api(path,opts){
  const r=await fetch(path,opts);
  let body=null;try{body=await r.json()}catch(e){}
  if(!r.ok)throw new Error((body&&body.detail)||('HTTP '+r.status));
  return body;
}
function say(el,text,ok){el.textContent=text;el.style.color=ok?'#12804a':'#c0392b'}

/* ---------- overview: KPIs, positions, orders, decisions ---------- */
async function loadOverview(){
  const x=await api('/ops/overview');const p=x.portfolio;state.portfolio=p;
  $('#kpis').innerHTML=[['Equity',money(p.equity),''],['Cash',money(p.cash),''],
    ['Realized P&L',signed(p.realized_pnl),cls(p.realized_pnl)],['Unrealized P&L',signed(p.unrealized_pnl),cls(p.unrealized_pnl)],
    ['Total P&L',signed(p.total_pnl),cls(p.total_pnl)],['Open orders',x.stats.open_orders,'']]
    .map(a=>`<div class="card kpi"><small>${a[0]}</small><div class="v ${a[2]}">${esc(a[1])}</div></div>`).join('');
  const w=x.worker;const pill=$('#workerPill');pill.textContent='worker '+w.status;pill.className='pill '+w.status;
  renderPositions(p.positions);
  const seen=[];const rows=[];
  for(const d of x.decisions){const k=d.market_id+'|'+d.reason+'|'+d.intents;if(seen[seen.length-1]===k)continue;seen.push(k);rows.push(d)}
  $('#decisions').innerHTML='<table><tr><th>Time</th><th>Market</th><th>Reason</th><th>Intents</th></tr>'+rows.slice(0,12).map(d=>`<tr><td>${esc(d.decision_time.slice(11,19))}</td><td>${esc(d.market_id)}</td><td>${esc(d.reason)}</td><td>${esc(summarize(d.intents))}</td></tr>`).join('')+'</table>';
  $('#replays').innerHTML=x.replays.length?'<table><tr><th>Started</th><th>Name</th><th>Status</th><th>Events</th><th>Net P&L</th></tr>'+x.replays.map(d=>`<tr><td>${esc(d.started_at)}</td><td>${esc(d.name)}</td><td>${esc(d.status)}</td><td>${esc(d.event_count)}</td><td>${esc(d.net_pnl)}</td></tr>`).join('')+'</table>':'<small>No replay runs yet.</small>';
}
function summarize(s){try{return JSON.parse(s).map(i=>`${i.side} ${i.token} ${i.quantity}@${i.price}`).join(', ')}catch(e){return s}}

function renderPositions(list){
  if(!list.length){$('#positions').innerHTML='<small>No open positions. Use BUY above, or wait for the strategy to fill an order.</small>';return}
  $('#positions').innerHTML='<table><tr><th>Market</th><th>Side</th><th>Shares</th><th>Entry</th><th>Mark (bid)</th><th>Value</th><th>Unrealized</th><th>Stop</th><th>Target</th><th></th></tr>'+
  list.map(p=>`<tr><td>${esc((p.question||'').slice(0,48))}</td><td>${esc(p.token)}</td><td>${f(p.quantity,2)}</td><td>${f(p.average_entry_price)}</td><td>${f(p.mark_price)}</td><td>${money(p.market_value)}</td>
  <td class="${cls(p.unrealized_pnl)}">${signed(p.unrealized_pnl)}</td><td>${f(p.stop_loss_price,2)}</td><td>${f(p.take_profit_price,2)} ${p.exit_status&&p.exit_status!=='active'?`<span class="tag ${esc(p.exit_status)}">${esc(p.exit_status.replace('_',' '))}</span>`:''}</td>
  <td><button data-sel="${p.market_id}|${esc(p.token)}">Select</button> <button data-close="${p.market_id}|${esc(p.token)}|${esc(p.quantity)}">Close</button></td></tr>`).join('')+'</table>';
}
$('#positions').addEventListener('click',async e=>{
  const sel=e.target.dataset.sel,cl=e.target.dataset.close;
  if(sel){const [m,t]=sel.split('|');await selectMarket(m);setToken(t)}
  if(cl){const [m,t,q]=cl.split('|');
    try{const r=await api('/paper/trade',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({market_id:+m,token:t,side:'SELL',quantity:q})});
      say($('#tradeMsg'),`Closed: sold ${f(r.quantity,2)} ${t} @ ${f(r.price)}`,true)}catch(err){say($('#tradeMsg'),err.message,false)}
    refresh()}
});

async function loadOrders(){
  const o=(await api('/orders?limit=60')).filter(o=>!['cancelled','rejected'].includes(o.status)||o.reject_reason);
  $('#orders').innerHTML=o.length?'<table><tr><th>Time</th><th>Market</th><th>Side</th><th>Token</th><th>Limit</th><th>Filled</th><th>Avg fill</th><th>Status</th></tr>'+
    o.slice(0,25).map(r=>`<tr><td>${esc((r.created_at||'').slice(11,19))}</td><td>${esc((r.question||'').slice(0,44))}</td><td>${esc(r.side)}</td><td>${esc(r.token)}</td><td>${f(r.price)}</td><td>${f(r.filled_quantity,2)}/${f(r.quantity,2)}</td><td>${f(r.average_fill_price)}</td><td>${esc(r.status)}${r.reject_reason?' — '+esc(r.reject_reason):''}</td></tr>`).join('')+'</table>':'<small>No orders yet.</small>';
}

/* ---------- live markets, quotes, chart ---------- */
async function loadLive(){
  state.live=await api('/live/markets');
  const sel=$('#marketSel');
  const held=new Set((state.portfolio?.positions||[]).map(p=>String(p.market_id)));
  const opts=state.live.map(m=>`<option value="${m.id}">${held.has(String(m.id))?'● ':''}${esc(m.question.slice(0,70))} — ${m.seconds_left>0?Math.floor(m.seconds_left/60)+'m '+(m.seconds_left%60)+'s left':'ended'}</option>`).join('');
  const cur=state.market;
  sel.innerHTML=opts||'<option>No live markets — start the worker</option>';
  if(!state.live.length)return;
  if(!cur||!state.live.some(m=>String(m.id)===String(cur)))state.market=state.live[0].id;
  sel.value=state.market;
}
async function selectMarket(id){state.market=id;await loadLive();await loadTicks()}
$('#marketSel').addEventListener('change',e=>{state.market=e.target.value;loadTicks()});

async function loadTicks(){
  if(!state.market){return}
  try{state.ticks=await api(`/live/markets/${state.market}/ticks`)}catch(e){return}
  const t=state.ticks,q=t.quote;
  $('#marketMeta').textContent=t.question+' · ends '+t.end_time.slice(11,19)+' UTC · last update '+(q?q.observed_at.slice(11,19):'—');
  $('#quotes').innerHTML=q?[['YES bid',q.yes_bid,'pos'],['YES ask',q.yes_ask,'pos'],['NO bid',q.no_bid,'neg'],['NO ask',q.no_ask,'neg']]
    .map(a=>`<div class="q"><small>${a[0]}</small><b class="${a[2]}">${f(a[1])}</b></div>`).join(''):'';
  updateTicket();draw();
}

function draw(){
  const cv=$('#chart'),dpr=window.devicePixelRatio||1,W=cv.clientWidth,H=cv.clientHeight;
  cv.width=W*dpr;cv.height=H*dpr;const c=cv.getContext('2d');c.scale(dpr,dpr);c.clearRect(0,0,W,H);
  const ticks=(state.ticks?.ticks||[]).map(k=>({t:Date.parse(k.t),y:num(k.yes),n:num(k.no)}));
  const L=44,R=12,T=10,B=24;
  c.font='11px system-ui';c.fillStyle='#64707d';
  if(ticks.length<2){c.fillText('Waiting for live ticks… (worker must be running)',L+10,H/2);return}
  const pos=(state.portfolio?.positions||[]).filter(p=>String(p.market_id)===String(state.market));
  const levels=[];pos.forEach(p=>{[['entry',p.average_entry_price],['sl',p.stop_loss_price],['tp',p.take_profit_price]].forEach(([k,v])=>{if(v!=null)levels.push({k,v:+v,tok:p.token})})});
  let vals=ticks.flatMap(k=>[k.y,k.n]).filter(v=>v!=null).concat(levels.map(l=>l.v));
  let lo=Math.min(...vals),hi=Math.max(...vals);const pad=Math.max(0.02,(hi-lo)*0.15);lo=Math.max(0,lo-pad);hi=Math.min(1,hi+pad);
  const t0=ticks[0].t,t1=ticks[ticks.length-1].t||t0+1;
  const X=t=>L+(t-t0)/Math.max(1,t1-t0)*(W-L-R),Y=v=>T+(1-(v-lo)/(hi-lo))*(H-T-B);
  c.strokeStyle='#edf0f2';c.lineWidth=1;
  for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4,y=Y(v);c.beginPath();c.moveTo(L,y);c.lineTo(W-R,y);c.stroke();c.fillText(v.toFixed(2),4,y+4)}
  for(let i=0;i<=4;i++){const t=t0+(t1-t0)*i/4;c.fillText(new Date(t).toISOString().slice(11,19),X(t)-20,H-6)}
  const line=(key,color)=>{c.strokeStyle=color;c.lineWidth=2;c.beginPath();let on=false;
    for(const k of ticks){if(k[key]==null)continue;const x=X(k.t),y=Y(k[key]);on?c.lineTo(x,y):c.moveTo(x,y);on=true}c.stroke()};
  line('y','#12804a');line('n','#c0392b');
  c.setLineDash([6,4]);c.lineWidth=1.5;
  for(const l of levels){c.strokeStyle=l.k==='sl'?'#c0392b':l.k==='tp'?'#12804a':'#64707d';const y=Y(l.v);
    c.beginPath();c.moveTo(L,y);c.lineTo(W-R,y);c.stroke();c.fillStyle=c.strokeStyle;c.fillText(`${l.k.toUpperCase()} ${l.tok} ${l.v.toFixed(2)}`,L+6,y-4)}
  c.setLineDash([]);
}
window.addEventListener('resize',draw);

/* ---------- trade ticket ---------- */
function setToken(t){state.token=t;document.querySelectorAll('#tokSeg button').forEach(b=>b.classList.toggle('on',b.dataset.t===t));updateTicket()}
$('#tokSeg').addEventListener('click',e=>{if(e.target.dataset.t)setToken(e.target.dataset.t)});
$('#qty').addEventListener('input',updateTicket);
function currentPosition(){return (state.portfolio?.positions||[]).find(p=>String(p.market_id)===String(state.market)&&p.token===state.token)}
function updateTicket(){
  const q=state.ticks?.quote,qty=num($('#qty').value)||0;if(!q)return;
  const ask=num(state.token==='YES'?q.yes_ask:q.no_ask);
  const b=num(state.token==='YES'?q.yes_bid:q.no_bid);
  $('#estimate').innerHTML=`BUY fills at ask <b>${f(ask)}</b> ≈ ${money(ask*qty)} · SELL fills at bid <b>${f(b)}</b> ≈ ${money(b*qty)}`;
  const p=currentPosition();
  $('#exitHint').textContent=p?`Holding ${f(p.quantity,2)} ${p.token} @ ${f(p.average_entry_price)}. Exits trigger on the ${p.token} bid.`:'Select a market where you hold shares.';
  for(const [id,v] of [['#sl',p?.stop_loss_price],['#tp',p?.take_profit_price]]){const el=$(id);if(document.activeElement!==el&&el.dataset.pos!==(p?p.market_id+p.token:'')){el.value=v!=null?Number(v).toFixed(2):'';}}
  $('#sl').dataset.pos=$('#tp').dataset.pos=p?p.market_id+p.token:'';
}
async function trade(side){
  const msg=$('#tradeMsg');
  try{const r=await api('/paper/trade',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({market_id:+state.market,token:state.token,side,quantity:$('#qty').value})});
    say(msg,`${side} filled: ${f(r.quantity,2)} ${r.token} @ ${f(r.price)}`,true)}catch(e){say(msg,e.message,false)}
  refresh();
}
$('#btnBuy').onclick=()=>trade('BUY');$('#btnSell').onclick=()=>trade('SELL');
$('#btnSetExit').onclick=async()=>{
  const body={market_id:+state.market,token:state.token,stop_loss_price:$('#sl').value||null,take_profit_price:$('#tp').value||null};
  try{await api('/paper/exits',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});say($('#exitMsg'),'Levels saved — the worker will close the position when hit.',true)}catch(e){say($('#exitMsg'),e.message,false)}
  refresh();
};
$('#btnClearExit').onclick=async()=>{
  try{await api(`/paper/exits/${state.market}/${state.token}`,{method:'DELETE'});$('#sl').value=$('#tp').value='';say($('#exitMsg'),'Levels cleared.',true)}catch(e){say($('#exitMsg'),e.message,false)}
  refresh();
};
async function worker(a){try{await api('/ops/worker/'+a,{method:'POST'})}catch(e){}refresh()}
$('#btnStart').onclick=()=>worker('start');$('#btnStop').onclick=()=>worker('stop');

async function refresh(){try{await loadOverview();await loadLive();await loadTicks();await loadOrders()}catch(e){console.error(e)}}
refresh();
setInterval(()=>{loadTicks().catch(()=>{})},1500);
setInterval(refresh,5000);
</script></body></html>
"""
