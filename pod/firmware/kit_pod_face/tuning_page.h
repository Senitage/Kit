// The servo tuning page the Pod serves at http://kit-pod.local (see kit_pod_face.ino).
// Plain HTML and JavaScript, no internet needed: it talks to the Pod's /move, /set,
// /save and /cmd addresses.
#pragma once

const char TUNING_PAGE[] PROGMEM = R"KITPAGE(<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kit Pod servos</title>
<style>
:root{--bg:#14161a;--card:#1e2127;--line:#2e333b;--text:#e8eaee;--dim:#9aa1ad;--glow:#4fe3c1;--warn:#f0a35e}
*{box-sizing:border-box}
body{margin:0;font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--text)}
main{max-width:760px;margin:0 auto;padding:16px}
h1{font-size:21px;margin:6px 0 2px}
h2{font-size:16px;margin:0 0 6px}
p{margin:6px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:12px 0}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}
button{background:#2a2f37;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 12px;font:inherit;cursor:pointer}
button:hover{border-color:var(--glow)}
button.main{background:var(--glow);color:#0b1412;border-color:var(--glow);font-weight:600}
input[type=range]{flex:1;min-width:180px;accent-color:var(--glow)}
input[type=number]{width:68px;background:#101216;color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px;font:inherit}
.big{font-size:22px;font-weight:600;min-width:64px;text-align:right;font-variant-numeric:tabular-nums}
.dim{color:var(--dim)}
.warn{color:var(--warn)}
#who{font-weight:600;color:var(--glow)}
ol{margin:6px 0 0 20px;padding:0}
li{margin:3px 0}
label{display:inline-flex;gap:6px;align-items:center}
</style></head><body><main>
<h1>Kit Pod servos</h1>
<p class="dim">The neck is with <span id="who">Kit</span>. <span id="note"></span></p>

<div class="card"><h2>1. Fit the horns</h2>
<div class="row"><button class="main" onclick="go('/fit')">Both servos to 90&deg; and hold</button></div>
<ol class="dim">
<li>Press the button. Both servos go to the middle of their travel and hold there.</li>
<li>Turn servo: push the neck on so Kit faces straight ahead. Tilt servo: slide it onto its horn with the head level.</li>
<li>A horn only goes on a whole spline tooth at a time, so you'll be a few degrees out. Fix that with Centre below.</li>
</ol></div>

<div class="card"><h2>2. Turn: looking left and right</h2>
<div class="row"><input type="range" id="turn" min="0" max="180" step="1"><span class="big" id="turnVal">90&deg;</span></div>
<div class="row"><button onclick="nudge('turn',-5)">&minus;5</button><button onclick="nudge('turn',-1)">&minus;1</button><button onclick="nudge('turn',1)">+1</button><button onclick="nudge('turn',5)">+5</button>
<button onclick="toEnd('turn',-1)">One end</button><button onclick="toEnd('turn',0)">Centre</button><button onclick="toEnd('turn',1)">Other end</button><button onclick="sweep('turn')">Sweep</button></div>
<div class="row"><span>Centre</span><button onclick="trim('tc',-1)">&minus;1</button><input type="number" id="tc" step="1" onchange="trim('tc',0)"><button onclick="trim('tc',1)">+1</button>
<span>Range &plusmn;</span><input type="number" id="tr" step="1" onchange="setCal()">
<label><input type="checkbox" id="ts" onchange="setCal()"> Flip direction</label></div>
<p class="dim">Centre: the angle where he faces straight ahead. Range: how far each way he may turn.</p></div>

<div class="card"><h2>3. Tilt: looking up and down</h2>
<div class="row"><input type="range" id="tilt" min="0" max="180" step="1"><span class="big" id="tiltVal">90&deg;</span></div>
<div class="row"><button onclick="nudge('tilt',-5)">&minus;5</button><button onclick="nudge('tilt',-1)">&minus;1</button><button onclick="nudge('tilt',1)">+1</button><button onclick="nudge('tilt',5)">+5</button>
<button onclick="toEnd('tilt',-1)">One end</button><button onclick="toEnd('tilt',0)">Centre</button><button onclick="toEnd('tilt',1)">Other end</button><button onclick="sweep('tilt')">Sweep</button></div>
<div class="row"><span>Centre</span><button onclick="trim('lc',-1)">&minus;1</button><input type="number" id="lc" step="1" onchange="trim('lc',0)"><button onclick="trim('lc',1)">+1</button>
<span>Range &plusmn;</span><input type="number" id="lr" step="1" onchange="setCal()">
<label><input type="checkbox" id="ls" onchange="setCal()"> Flip direction</label></div>
<p class="dim">Centre: the angle where his head is level. The printed head can nod 18&deg; each way. To find the real limit,
tick Free movement below, nudge 1&deg; at a time until the head just touches, and set Range a couple of degrees less.</p></div>

<div class="card"><h2>4. Check with Kit</h2>
<p class="dim">These give the neck back to Kit. His eyes move first and the head should follow the same way.
If the head goes the opposite way to his eyes, tick Flip direction for that servo and try again.</p>
<div class="row"><button onclick="cmd('look -1 0')">Look left</button><button onclick="cmd('look 1 0')">Look right</button>
<button onclick="cmd('look 0 -1')">Look up</button><button onclick="cmd('look 0 1')">Look down</button>
<button onclick="cmd('nod')">Nod</button><button onclick="cmd('shake')">Shake</button><button onclick="cmd('glance')">Glance round</button></div></div>

<div class="card"><h2>5. Keep it</h2>
<div class="row"><button class="main" onclick="go('/save')">Save in the Pod</button><button onclick="go('/release')">Give the neck back to Kit</button>
<button onclick="if(confirm('Go back to the starting values (90, 90, ranges 35 and 18)?'))go('/defaults')">Starting values</button></div>
<div class="row"><label><input type="checkbox" id="free" onchange="go('/free?on='+(this.checked?1:0))">
<span>Free movement: anywhere from 0 to 180&deg;. <span class="warn">Careful, the head can hit the body.</span></span></label></div>
<p class="dim">Keys: &larr; &rarr; turn, &uarr; &darr; tilt (they follow Kit's directions once Flip direction is right), Shift for 5&deg;, Esc gives the neck back.
Saved settings stay in the Pod through restarts and new uploads.</p></div>
</main>
<script>
const $ = id => document.getElementById(id);
const SPEED = 60;  // degrees a second, as in the Pod
let st = {turn: 90, tilt: 90, tc: 90, tr: 35, ts: 1, lc: 90, lr: 18, ls: 1}, dragging = null;

async function go(url) {
  try {
    const r = await fetch(url);
    st = await r.json();
    show();
  } catch (e) {
    $('note').textContent = "Can't reach the Pod. Is it on?";
  }
}

function show() {
  $('who').textContent = st.tuning ? 'you' : 'Kit';
  $('note').textContent = st.note || (st.tuning
    ? 'Kit takes it back 15 s after you close this page.'
    : 'Move anything here to take it.');
  for (const [k, c, r] of [['turn', 'tc', 'tr'], ['tilt', 'lc', 'lr']]) {
    const s = $(k);
    s.min = st.free ? 0 : Math.max(0, Math.round(st[c] - st[r]));
    s.max = st.free ? 180 : Math.min(180, Math.round(st[c] + st[r]));
    if (dragging !== k) s.value = Math.round(st[k]);
    $(k + 'Val').textContent = Math.round(st[k]) + '°';
  }
  for (const k of ['tc', 'tr', 'lc', 'lr']) if (document.activeElement !== $(k)) $(k).value = Math.round(st[k]);
  $('ts').checked = st.ts < 0;
  $('ls').checked = st.ls < 0;
  $('free').checked = st.free;
}

// Sliders: send where they are at most every 80 ms while dragging.
let lastSent = 0, pending = null;
function moveTo(k, v) {
  pending = k + '=' + v;
  const wait = Math.max(0, 80 - (Date.now() - lastSent));
  setTimeout(() => {
    if (!pending) return;
    const q = pending;
    pending = null;
    lastSent = Date.now();
    go('/move?' + q);
  }, wait);
}
for (const k of ['turn', 'tilt']) {
  const s = $(k);
  s.addEventListener('input', () => { dragging = k; moveTo(k, s.value); });
  s.addEventListener('change', () => { dragging = null; moveTo(k, s.value); });
}

function nudge(k, d) { go('/move?d' + k + '=' + d); }
function ends(k) { return k === 'turn' ? [st.tc, st.tr] : [st.lc, st.lr]; }
function toEnd(k, side) { const [c, r] = ends(k); go('/move?' + k + '=' + (c + side * r)); }
const sleep = ms => new Promise(res => setTimeout(res, ms));
async function sweep(k) {
  const [c, r] = ends(k);
  let at = st[k];
  for (const to of [c - r, c + r, c]) {
    await go('/move?' + k + '=' + to);
    await sleep(Math.abs(to - at) / SPEED * 1000 + 500);
    at = to;
  }
}

function calQuery() {
  return 'tc=' + $('tc').value + '&tr=' + $('tr').value + '&ts=' + ($('ts').checked ? -1 : 1) +
         '&lc=' + $('lc').value + '&lr=' + $('lr').value + '&ls=' + ($('ls').checked ? -1 : 1);
}
async function setCal() { await go('/set?' + calQuery()); }
// Change a centre and go there, so you see the head straighten.
async function trim(k, d) {
  $(k).value = Number($(k).value) + d;
  await setCal();
  go('/centre');
}
function cmd(c) { go('/cmd?c=' + encodeURIComponent(c)); }

document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' && e.target.type === 'number') return;
  const step = e.shiftKey ? 5 : 1;
  // On the Pod, looking to your left is +turn sign and looking up is -tilt sign.
  const keys = {ArrowLeft: ['turn', st.ts * step], ArrowRight: ['turn', -st.ts * step],
                ArrowUp: ['tilt', -st.ls * step], ArrowDown: ['tilt', st.ls * step]};
  if (keys[e.key]) { e.preventDefault(); nudge(keys[e.key][0], keys[e.key][1]); }
  if (e.key === 'Escape') go('/release');
});

// Keep the neck while this page is open and has it; a hidden tab lets it go.
setInterval(() => { if (!document.hidden) go(st.tuning ? '/state?hold=1' : '/state'); }, 1500);
go('/state');
</script></body></html>)KITPAGE";
