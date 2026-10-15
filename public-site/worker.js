// Public, read-only page of what the Ryciny add-on hears: birds, heard planes and neighbourhood sounds.
// The add-on pushes a trimmed journal (no audio, no dogs, no speech, no location) and each engraving once;
// visitors only ever read from KV, nothing reaches the home network.

const ART_KINDS = new Set(["BIRD", "PLANE", "SCENE"]);

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    const path = url.pathname;

    if (path.startsWith("/ingest/")) {
      if (req.headers.get("Authorization") !== `Bearer ${env.INGEST_TOKEN}`) return new Response("no", { status: 401 });
      if (req.method !== "PUT") return new Response("PUT only", { status: 405 });
      if (path === "/ingest/state") {
        const state = await req.json();
        await env.DATA.put("state", JSON.stringify(state));
        return Response.json({ ok: true });
      }
      if (path === "/ingest/art") {
        const kind = url.searchParams.get("kind"), key = url.searchParams.get("key");
        if (!ART_KINDS.has(kind) || !key) return new Response("kind and key", { status: 400 });
        const type = req.headers.get("Content-Type") || "image/png";
        await env.DATA.put(`art:${kind}:${key}`, await req.arrayBuffer(), { metadata: { type } });
        return Response.json({ ok: true });
      }
      if (path === "/ingest/has") {
        // Which engravings are already up, so the add-on uploads each one only once even after a restart.
        const list = [];
        let cursor;
        do {
          const page = await env.DATA.list({ prefix: "art:", cursor });
          list.push(...page.keys.map(k => k.name.slice(4)));
          cursor = page.list_complete ? undefined : page.cursor;
        } while (cursor);
        return Response.json(list);
      }
      return new Response("not found", { status: 404 });
    }

    if (path === "/api/state") {
      const state = await env.DATA.get("state");
      return new Response(state || "{}", {
        headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "public, max-age=60" },
      });
    }

    if (path === "/art") {
      const cache = caches.default;
      const hit = await cache.match(req);
      if (hit) return hit;
      const kind = url.searchParams.get("kind"), key = url.searchParams.get("key");
      const { value, metadata } = await env.DATA.getWithMetadata(`art:${kind}:${key}`, { type: "arrayBuffer" });
      if (!value) return new Response("missing", { status: 404, headers: { "Cache-Control": "public, max-age=300" } });
      const res = new Response(value, {
        headers: { "Content-Type": metadata?.type || "image/png", "Cache-Control": "public, max-age=31536000, immutable" },
      });
      ctx.waitUntil(cache.put(req, res.clone()));
      return res;
    }

    if (path === "/" || path === "/index.html") {
      return new Response(PAGE, { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "public, max-age=300" } });
    }
    return new Response("not found", { status: 404 });
  },
};

const PAGE = `<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dźwięki Dolnego Migowa</title>
<meta name="description" content="Co ćwierka, przelatuje i słychać na Dolnym Migowie w Gdańsku: ptaki rozpoznane przez BirdNET, samoloty i dźwięki okolicy, na żywo, z rycinami.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">
<style>
:root{--paper:#f3ead8;--ink:#2b2118;--soft:#7a6a58;--rubric:#9b3a26;--rule:#2b211833;--card:#fbf6ea}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--paper:#1f1a14;--ink:#efe4cf;--soft:#b3a48c;--rubric:#e08b6f;--rule:#efe4cf33;--card:#2a231b}}
:root[data-theme="dark"]{--paper:#1f1a14;--ink:#efe4cf;--soft:#b3a48c;--rubric:#e08b6f;--rule:#efe4cf33;--card:#2a231b}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:18px/1.45 "EB Garamond",Georgia,serif}
main{max-width:860px;margin:0 auto;padding:22px 16px 60px}
h1{font-weight:400;text-align:center;font-size:34px;margin:6px 0 0}
.sub{text-align:center;color:var(--soft);font-style:italic;margin:0 0 18px}
h2{font-weight:400;font-size:24px;border-bottom:1px solid var(--rule);margin:34px 0 10px;padding-bottom:4px}
.plate{background:var(--card);border:1px solid var(--rule);outline:1px solid var(--rule);outline-offset:-8px;padding:22px 18px;text-align:center}
.plate img{max-width:100%;max-height:420px;object-fit:contain;mix-blend-mode:multiply}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]) .plate img{mix-blend-mode:normal}}
.plate .t{font-size:30px;margin-top:8px}
.plate .l{color:var(--soft);font-style:italic}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.stat{background:var(--card);border:1px solid var(--rule);padding:10px;text-align:center}
.stat b{display:block;font-size:30px;font-weight:600;color:var(--rubric)}
.top{list-style:none;padding:0;margin:0;columns:2 260px}
.top li{break-inside:avoid;display:flex;align-items:center;gap:8px;margin:2px 0}
.bar{height:8px;background:var(--rubric);opacity:.75}
.hours{display:flex;align-items:flex-end;gap:2px;height:90px;border-bottom:1px solid var(--rule)}
.hours div{flex:1;background:var(--rubric);opacity:.7;min-height:1px}
.hlab{display:flex;justify-content:space-between;color:var(--soft);font-size:13px}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.filters button{font:inherit;font-size:16px;background:none;border:1px solid var(--rule);color:var(--ink);padding:2px 12px;border-radius:14px;cursor:pointer}
.filters button.on{background:var(--ink);color:var(--paper)}
.filters button:disabled{opacity:.35;cursor:default}
.pager{margin-top:14px;justify-content:center;align-items:center}
.filters.top{position:sticky;top:0;z-index:2;background:var(--paper);justify-content:center;padding:8px 0;margin:0 0 12px;border-bottom:1px solid var(--rule)}
.row{display:flex;gap:12px;align-items:center;padding:7px 0;border-bottom:1px solid var(--rule)}
.thumb{width:58px;height:58px;object-fit:contain;flex:none;mix-blend-mode:multiply}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]) .thumb{mix-blend-mode:normal}}
.thumb.empty{border:1px dashed var(--rule)}
.d{color:var(--soft);font-style:italic;font-size:15px}
.soft{color:var(--soft)}
footer{margin-top:40px;color:var(--soft);font-size:14px;text-align:center}
a{color:var(--rubric)}
</style>
</head>
<body>
<main>
  <h1>Dźwięki Dolnego Migowa</h1>
  <p class="sub">Gdańsk · mikrofon za oknem słucha ptaków, samolotów i okolicy · <span id="upd">…</span></p>
  <nav class="filters top" id="filters"></nav>
  <section class="plate" id="plate"><p class="soft">Wczytuję…</p></section>

  <h2>Statystyki</h2>
  <div class="stats" id="stats"></div>
  <div id="birdstats">
  <h3 style="font-weight:400">Najczęściej słyszane ptaki (7 dni)</h3>
  <ul class="top" id="top"></ul>
  <h3 style="font-weight:400">Ptaki według godziny (7 dni)</h3>
  <div class="hours" id="hours"></div>
  <div class="hlab"><span>0:00</span><span>6:00</span><span>12:00</span><span>18:00</span><span>23:00</span></div>
  </div>

  <h2 id="dziennik">Dziennik</h2>
  <div id="entries"></div>
  <nav class="filters pager" id="pager"></nav>

  <footer>
    Rozpoznawanie: <a href="https://birdnet.cornell.edu/">BirdNET</a> i YAMNet, na komputerze w domu; pewność to ocena modelu,
    nie obserwacja ornitologa. Ryciny ptaków: <a href="https://fugleramme.no/">fugleramme</a> (CC BY-SA 4.0) i tablice z domeny
    publicznej; ryciny samolotów i dźwięków generowane. Samoloty: adsb.lol, adsbdb. Nie ma tu nagrań dźwięku.
    · <a href="https://github.com/qunabu/ryciny">Ryciny na GitHubie</a>
  </footer>
</main>
<script>
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
const PL = 'pl-PL';
const hhmm = t => new Date(t).toLocaleTimeString(PL, {hour: '2-digit', minute: '2-digit'});
const day = t => { const d = new Date(t), n = new Date(); const y = new Date(n); y.setDate(n.getDate() - 1);
  return d.toDateString() === n.toDateString() ? 'dziś' : d.toDateString() === y.toDateString() ? 'wczoraj' : d.toLocaleDateString(PL, {day: 'numeric', month: 'short'}); };
const art = (kind, key, cls = 'thumb') => '<img class="' + cls + '" loading="lazy" alt="" src="art?kind=' + kind + '&key=' + encodeURIComponent(key) + '" onerror="this.outerHTML=\\'<div class=&quot;' + cls + ' empty&quot;></div>\\'">';
const FILTERS = [['all', 'wszystko', ''], ['birds', 'ptaki', 'ptaki'], ['planes', 'samoloty', 'samoloty'], ['sounds', 'dźwięki', 'dzwieki']];
const fromHash = () => (FILTERS.find(f => f[2] && '#' + f[2] === location.hash) || FILTERS[0])[0];
let state = null, filter = fromHash(), page = 0;
addEventListener('hashchange', () => { filter = fromHash(); page = 0; render(); });
const PAGE = 25;

async function load() {
  try {
    const r = await fetch('api/state', {cache: 'no-cache'});
    state = await r.json();
    render();
  } catch (e) { $('#upd').textContent = 'brak połączenia'; }
}

function newest() {
  const s = state, items = [];
  const on = k => filter === 'all' || filter === k;
  if (on('birds')) s.birds.forEach(b => items.push({at: b.lastAt, kind: 'BIRD', key: b.sci, title: b.name, lines: [b.sci, 'ostatnio ' + hhmm(b.lastAt)]}));
  if (on('planes')) s.planes.forEach(p => items.push({at: p.at, kind: 'PLANE', key: p.art, title: p.title,
    lines: [[p.airline, p.callsign].filter(Boolean).join(' · '), p.route, 'słychać było o ' + hhmm(p.at)]}));
  if (on('sounds')) s.sounds.forEach(e => items.push({at: e.at, kind: 'SCENE', key: e.art, title: e.label,
    lines: [e.title, e.subtitle, hhmm(e.at) + '–' + hhmm(e.lastAt)]}));
  return items.sort((a, b) => b.at - a.at)[0];
}

function render() {
  const s = state;
  if (!s || !s.birds) { $('#plate').innerHTML = '<p class="soft">Jeszcze nic tu nie ma.</p>'; return; }
  $('#upd').textContent = 'aktualizacja ' + day(s.updatedAt) + ' ' + hhmm(s.updatedAt);
  const n = newest();
  $('#plate').innerHTML = n ? art(n.kind, n.key, 'big') + '<div class="t">' + esc(n.title.charAt(0).toUpperCase() + n.title.slice(1)) + '</div>' +
    n.lines.filter(Boolean).map(l => '<div class="l">' + esc(l) + '</div>').join('') : '<p class="soft">Cisza.</p>';

  const week = Date.now() - 7 * 864e5, today = new Date(); today.setHours(0, 0, 0, 0);
  const b7 = s.birds.filter(b => b.lastAt >= week), bToday = s.birds.filter(b => b.lastAt >= today);
  const species = l => new Set(l.map(b => b.sci)).size;
  const stat = (v, l) => '<div class="stat"><b>' + v + '</b>' + l + '</div>';
  const pToday = s.planes.filter(p => p.at >= today), sToday = s.sounds.filter(e => e.lastAt >= today);
  const birdStats = stat(species(bToday), 'gatunków ptaków dziś') + stat(species(b7), 'gatunków w 7 dni') + stat(species(s.birds), 'gatunków w 30 dni');
  const planeStats = stat(pToday.length, 'usłyszanych samolotów dziś') + stat(s.planes.filter(p => p.at >= week).length, 'samolotów w 7 dni') +
    stat(new Set(pToday.map(p => p.airline).filter(Boolean)).size, 'linii lotniczych dziś');
  const soundStats = stat(new Set(sToday.map(e => e.key)).size, 'rodzajów dźwięków dziś') + stat(sToday.filter(e => e.key === 'train').length, 'pociągów dziś') +
    stat(s.sounds.filter(e => e.lastAt >= week).length, 'dźwięków w 7 dni');
  $('#stats').innerHTML = filter === 'birds' ? birdStats : filter === 'planes' ? planeStats : filter === 'sounds' ? soundStats
    : birdStats + stat(pToday.length, 'usłyszanych samolotów dziś');
  $('#birdstats').style.display = filter === 'all' || filter === 'birds' ? '' : 'none';

  const bySp = {};
  b7.forEach(b => { const k = b.sci; (bySp[k] ||= {name: b.name, sci: k, n: 0}).n += b.count; });
  const top = Object.values(bySp).sort((a, b) => b.n - a.n).slice(0, 12), max = top[0]?.n || 1;
  $('#top').innerHTML = top.map(t => '<li>' + art('BIRD', t.sci) + '<span style="flex:1">' + esc(t.name) +
    '<div class="bar" style="width:' + Math.max(4, 100 * t.n / max) + '%"></div></span><span class="soft">' + t.n + '×</span></li>').join('') ||
    '<li class="soft">Jeszcze brak.</li>';

  const hours = Array(24).fill(0);
  b7.forEach(b => hours[new Date(b.lastAt).getHours()] += b.count);
  const hm = Math.max(1, ...hours);
  $('#hours').innerHTML = hours.map((v, h) => '<div title="' + h + ':00 · ' + v + '×" style="height:' + (100 * v / hm) + '%"></div>').join('');

  $('#filters').innerHTML = FILTERS.map(([k, l]) => '<button class="' + (k === filter ? 'on' : '') + '" data-f="' + k + '">' + l + '</button>').join('');
  $('#filters').querySelectorAll('button').forEach(b => b.onclick = () => {
    filter = b.dataset.f; page = 0;
    history.replaceState(null, '', location.pathname + (FILTERS.find(f => f[0] === filter)[2] ? '#' + FILTERS.find(f => f[0] === filter)[2] : ''));
    render();
  });
  const rows = [];
  if (filter === 'all' || filter === 'birds') s.birds.forEach(b => rows.push({at: b.lastAt, html: '<div class="row">' + art('BIRD', b.sci) +
    '<div>' + esc(b.name.charAt(0).toUpperCase() + b.name.slice(1)) + '<div class="d">' + day(b.lastAt) + ' ' + hhmm(b.lastAt) + ' · ' + esc(b.sci) +
    ' · ' + Math.round(b.conf * 100) + '%' + (b.count > 1 ? ' · ' + b.count + '×' : '') + '</div></div></div>'}));
  if (filter === 'all' || filter === 'planes') s.planes.forEach(p => rows.push({at: p.lastAt, html: '<div class="row">' + art('PLANE', p.art) +
    '<div>' + esc(p.title) + (p.callsign ? ' · ' + esc(p.callsign) : '') + '<div class="d">' +
    esc([day(p.at) + ' ' + hhmm(p.at), p.airline, p.route, p.altM ? p.altM + ' m' : ''].filter(Boolean).join(' · ')) + '</div></div></div>'}));
  if (filter === 'all' || filter === 'sounds') s.sounds.forEach(e => rows.push({at: e.lastAt, html: '<div class="row">' + art('SCENE', e.art) +
    '<div>' + esc(e.label) + (e.title ? ': ' + esc(e.title) : '') + '<div class="d">' + day(e.at) + ' ' + hhmm(e.at) + '–' + hhmm(e.lastAt) +
    (e.subtitle ? ' · ' + esc(e.subtitle) : '') + '</div></div></div>'}));
  rows.sort((a, b) => b.at - a.at);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  page = Math.min(page, pages - 1);
  $('#entries').innerHTML = rows.slice(page * PAGE, (page + 1) * PAGE).map(r => r.html).join('') || '<p class="soft">Jeszcze pusto.</p>';
  $('#pager').innerHTML = pages < 2 ? '' : pager(pages);
  $('#pager').querySelectorAll('button[data-p]').forEach(b => b.onclick = () => { page = +b.dataset.p; render(); $('#dziennik').scrollIntoView({behavior: 'smooth'}); });
}

// ‹ nowsze 1 … 4 5 6 … 20 starsze ›
function pager(pages) {
  const btn = (p, label, on = false, off = false) => '<button data-p="' + p + '"' + (off ? ' disabled' : '') + ' class="' + (on ? 'on' : '') + '">' + label + '</button>';
  const show = new Set([0, pages - 1, page - 1, page, page + 1].filter(p => p >= 0 && p < pages));
  let out = btn(page - 1, '‹ nowsze', false, page === 0), last = -1;
  [...show].sort((a, b) => a - b).forEach(p => { if (p - last > 1) out += '<span class="soft">…</span>'; out += btn(p, p + 1, p === page); last = p; });
  return out + btn(page + 1, 'starsze ›', false, page === pages - 1) + '<span class="soft"> ' + rows_label(pages) + '</span>';
}
const rows_label = pages => 'strona ' + (page + 1) + ' z ' + pages;

load();
setInterval(load, 60000);
</script>
<style>.big{max-width:100%;max-height:420px;object-fit:contain}.big.empty{height:200px;border:none}</style>
</body>
</html>`;
