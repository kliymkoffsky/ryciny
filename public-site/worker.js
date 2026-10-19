// Public, read-only page of what the Ryciny add-on hears: birds, heard planes and neighbourhood sounds.
// The add-on pushes a trimmed journal (no audio, no dogs, no speech, no location) and each engraving once;
// visitors only ever read from KV, nothing reaches the home network.

const ART_KINDS = new Set(["BIRD", "PLANE", "SCENE"]);
const CLIP = /^[0-9a-f]{8}\.(wav|mp3)$/;
const CLIP_TTL_S = 14 * 86400; // bird recordings disappear from KV after 14 days

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
      if (path === "/ingest/clip") {
        const name = url.searchParams.get("name") || "";
        if (!CLIP.test(name)) return new Response("name", { status: 400 });
        // A species' best recording (keep=1) stays until a better one replaces it; the old one expires in a year.
        const ttl = url.searchParams.get("keep") === "1" ? 400 * 86400 : CLIP_TTL_S;
        await env.DATA.put(`clip:${name}`, await req.arrayBuffer(), { expirationTtl: ttl });
        return Response.json({ ok: true });
      }
      if (path === "/ingest/anim") {
        // A prepared animation: six frames side by side (64 hex id = the pack's content hash, so it never changes).
        const id = url.searchParams.get("id") || "";
        if (!/^[0-9a-f]{64}$/.test(id)) return new Response("id", { status: 400 });
        // poster=1: frame one alone, the still for small engravings.
        await env.DATA.put(url.searchParams.get("poster") === "1" ? `animp:${id}` : `anim:${id}`, await req.arrayBuffer());
        return Response.json({ ok: true });
      }
      if (path === "/ingest/has") {
        // What is already up, so the add-on uploads each engraving and recording only once even after a restart:
        // "KIND:key" for engravings, "clip:name" for recordings.
        const list = [];
        for (const prefix of ["art:", "clip:", "anim:", "animp:"]) {
          let cursor;
          do {
            const page = await env.DATA.list({ prefix, cursor });
            list.push(...page.keys.map(k => prefix === "art:" ? k.name.slice(4) : k.name));
            cursor = page.list_complete ? undefined : page.cursor;
          } while (cursor);
        }
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

    if (path === "/clip") {
      const name = url.searchParams.get("name") || "";
      if (!CLIP.test(name)) return new Response("name", { status: 400 });
      const cache = caches.default;
      const hit = await cache.match(req);
      if (hit) return hit;
      const value = await env.DATA.get(`clip:${name}`, { type: "arrayBuffer" });
      if (!value) return new Response("missing", { status: 404 });
      const type = name.endsWith(".mp3") ? "audio/mpeg" : "audio/wav";
      const res = new Response(value, { headers: { "Content-Type": type, "Cache-Control": "public, max-age=86400" } });
      ctx.waitUntil(cache.put(req, res.clone()));
      return res;
    }

    if (path === "/anim") {
      const id = url.searchParams.get("id") || "";
      if (!/^[0-9a-f]{64}$/.test(id)) return new Response("id", { status: 400 });
      const cache = caches.default;
      const hit = await cache.match(req);
      if (hit) return hit;
      const value = await env.DATA.get(url.searchParams.get("poster") === "1" ? `animp:${id}` : `anim:${id}`, { type: "arrayBuffer" });
      if (!value) return new Response("missing", { status: 404 });
      const res = new Response(value, { headers: { "Content-Type": "image/png", "Cache-Control": "public, max-age=31536000, immutable" } });
      ctx.waitUntil(cache.put(req, res.clone()));
      return res;
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
.top li,.row{cursor:default}
.top li{break-inside:avoid;display:flex;align-items:center;gap:8px;margin:2px 0}
.bar{height:8px;background:var(--rubric);opacity:.75}
.hours{display:flex;align-items:flex-end;gap:2px;height:90px;border-bottom:1px solid var(--rule)}
.hours div{flex:1;background:var(--rubric);opacity:.7;min-height:1px}
.hlab{display:flex;justify-content:space-between;color:var(--soft);font-size:13px}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.filters button{font:inherit;font-size:16px;background:none;border:1px solid var(--rule);color:var(--ink);padding:2px 12px;border-radius:14px;cursor:pointer}
.filters button.on{background:var(--ink);color:var(--paper)}
.filters .pause{margin-left:12px;border-style:dashed}
.filters button:disabled{opacity:.35;cursor:default}
.plate .nav{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:-6px 0 8px;font-size:15px}
.arrow{font:inherit;font-size:16px;background:none;border:1px solid var(--rule);color:var(--ink);padding:2px 12px;border-radius:14px;cursor:pointer}
.arrow:disabled{opacity:.3;cursor:default}
.top a,.row a{color:inherit;text-decoration-color:var(--rule)}
.pager{margin-top:14px;justify-content:center;align-items:center}
.filters.top{position:sticky;top:0;z-index:2;background:var(--paper);justify-content:center;padding:8px 0;margin:0 0 12px;border-bottom:1px solid var(--rule)}
.play{font:inherit;font-size:16px;background:none;border:1px solid var(--rule);color:var(--rubric);border-radius:50%;width:34px;height:34px;cursor:pointer;flex:none;margin-left:auto}
.top li .play{margin-left:8px;width:30px;height:30px;font-size:13px}
.d .play{width:26px;height:26px;font-size:12px;margin-left:4px;vertical-align:middle}
.play.on{background:var(--rubric);color:var(--paper)}
.row{display:flex;gap:12px;align-items:center;padding:7px 0;border-bottom:1px solid var(--rule)}
.anim{background-size:600% 100%;background-repeat:no-repeat;background-position:0 0;mix-blend-mode:multiply}
.anim{display:inline-block;vertical-align:middle}
.big.anim{height:min(420px, 56vw);width:auto;max-width:100%}
.thumb.anim{height:58px;width:auto;flex:none}
.tbox{width:58px;height:58px;flex:none;display:inline-flex;align-items:center;justify-content:center}
.tbox .still,.tbox .anim{mix-blend-mode:multiply;display:block}
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
  <div id="chance"></div>
  <h3 style="font-weight:400">Ptaki według godziny (7 dni)</h3>
  <div class="hours" id="hours"></div>
  <div class="hlab"><span>0:00</span><span>6:00</span><span>12:00</span><span>18:00</span><span>23:00</span></div>
  </div>

  <h2 id="dziennik">Dziennik</h2>
  <div id="entries"></div>
  <nav class="filters pager" id="pager"></nav>

  <h2>Jak to jest nagrywane</h2>
  <p>Mikrofon <b>Primo EM272</b> (kapsuła elektretowa wielokierunkowa, mikrofon krawatowy Micverve) wisi za oknem.
  Przez kartę dźwiękową USB <b>UGREEN US205</b> (48 kHz) trafia do małego komputera <b>Intel NUC</b> z Home Assistant,
  który słucha całą dobę. Co 3 sekundy nagranie przechodzi przez <b>BirdNET</b> (ptaki) i <b>YAMNet</b> (pozostałe
  dźwięki). Samoloty są porównywane z danymi ADS-B, a pociągi z rozkładem PKP PLK. Na stronę trafia to, co zostało
  rozpoznane, z 9-sekundowym nagraniem (▶), ale tylko takim, w którym model nie usłyszał ludzi ani muzyki; rozmów i
  dzieci nie nagrywamy wcale. Po 14 dniach nagrania znikają.</p>
  <footer>
    Rozpoznawanie: <a href="https://birdnet.cornell.edu/">BirdNET</a> i YAMNet, na komputerze w domu; pewność to ocena modelu,
    nie obserwacja ornitologa. Ryciny ptaków: <a href="https://fugleramme.no/">fugleramme</a> (CC BY-SA 4.0) i tablice z domeny
    publicznej; ryciny samolotów i dźwięków generowane. Samoloty: adsb.lol, adsbdb. Nagrania 9 s, sprawdzane automatycznie, czy nie słychać w nich ludzi ani muzyki; 14 dni.
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
// Moving engravings (prepared six-frame strips): a sprite stepped by one ticker; still images when motion is reduced.
const still = matchMedia('(prefers-reduced-motion: reduce)');
const animOf = (kind, key) => state && state.animations && state.animations[kind + ':' + key];
const moving = (a, cls) => '<div class="' + cls + ' anim" role="img" style="aspect-ratio:' + a.w + '/' + a.h +
  ';background-image:url(anim?id=' + a.id + ')"></div>';
// The big plate moves all the time; small engravings stay still and move only under the pointer (the strip
// is loaded then, not with the page).
let frame = 0;
// The pause button at the top: kept in this browser only.
let paused = false;
try { paused = localStorage.getItem('ryciny-paused') === '1'; } catch (e) {}
function togglePause() {
  paused = !paused;
  try { localStorage.setItem('ryciny-paused', paused ? '1' : '0'); } catch (e) {}
  pauseLabel();
}
function pauseLabel() {
  const b = document.getElementById('pause');
  if (b) { b.textContent = paused ? '▶ animacje' : '❚❚ zatrzymaj animacje'; b.setAttribute('aria-pressed', paused ? 'true' : 'false'); }
}
setInterval(() => {
  if (paused || still.matches || document.hidden) return;
  frame = (frame + 1) % 6;
  document.querySelectorAll('.big.anim, .anim.hover').forEach(el => el.style.backgroundPosition = (frame * 20) + '% 0');
}, 180);
// A small engraving with an animation: frame one as the still, in a box of the frame's own proportions, so the
// moving strip that replaces it on hover covers exactly the same pixels.
const box = (a, side) => { const r = a.w / a.h; return r >= 1 ? [side, Math.round(side / r)] : [Math.round(side * r), side]; };
const art = (kind, key, cls = 'thumb') => {
  const a = animOf(kind, key);
  if (!a) return stillArt(kind, key, cls);
  if (cls === 'big') return moving(a, cls);
  const [w, h] = box(a, 58);
  return '<span class="tbox"><img class="still" alt="" loading="lazy" src="anim?id=' + a.id + '&poster=1" style="width:' + w + 'px;height:' + h +
    'px" data-anim="' + a.id + '"></span>';
};
// The whole row is the hover area: its engraving moves while the pointer is anywhere on the row.
const rowOf = el => el && el.closest && el.closest('.top li, .row');
document.addEventListener('pointerover', e => {
  const row = rowOf(e.target);
  const img = row && row.querySelector('img[data-anim]');
  if (!img || still.matches || paused) return;
  const div = document.createElement('div');
  div.className = 'anim hover';
  div.style.cssText = 'width:' + img.style.width + ';height:' + img.style.height + ';background-image:url(anim?id=' + img.dataset.anim + ')';
  div.dataset.still = img.outerHTML;
  img.replaceWith(div);
});
document.addEventListener('pointerout', e => {
  const row = rowOf(e.target);
  if (!row || (e.relatedTarget && row.contains(e.relatedTarget))) return;
  row.querySelectorAll('.anim.hover').forEach(div => { div.outerHTML = div.dataset.still; });
});
const stillArt = (kind, key, cls = 'thumb') => '<img class="' + cls + '" loading="lazy" alt="" src="art?kind=' + kind + '&key=' + encodeURIComponent(key) + '" onerror="this.outerHTML=\\'<div class=&quot;' + cls + ' empty&quot;></div>\\'">';
const FILTERS = [['all', 'wszystko', ''], ['birds', 'ptaki', 'ptaki'], ['planes', 'samoloty', 'samoloty'], ['sounds', 'dźwięki', 'dzwieki']];
const fromHash = () => (FILTERS.find(f => f[2] && '#' + f[2] === location.hash) || FILTERS[0])[0];
let state = null, filter = fromHash(), page = 0;
addEventListener('hashchange', () => { filter = fromHash(); page = 0; shown = null; render(); });
const PAGE = 25;

async function load() {
  try {
    const r = await fetch('api/state', {cache: 'no-cache'});
    state = await r.json();
    render();
  } catch (e) { $('#upd').textContent = 'brak połączenia'; }
}

const wiki = sci => 'https://pl.wikipedia.org/wiki/Special:Search?go=Go&search=' + encodeURIComponent(sci);
let player = null;
const playBtn = name => name ? '<button class="play" title="Posłuchaj" data-n="' + name + '" onclick="play(this)">▶</button>' : '';
function play(btn) {
  const name = btn.dataset.n;
  if (player) { player.pause(); document.querySelectorAll('.play.on').forEach(b => { b.classList.remove('on'); b.textContent = '▶'; }); }
  if (btn.dataset.playing) { delete btn.dataset.playing; player = null; return; }
  document.querySelectorAll('.play[data-playing]').forEach(b => delete b.dataset.playing);
  player = new Audio('clip?name=' + name);
  btn.dataset.playing = '1'; btn.classList.add('on'); btn.textContent = '■';
  player.onended = () => { delete btn.dataset.playing; btn.classList.remove('on'); btn.textContent = '▶'; };
  player.play();
}
const wikiLink = (sci, label) => '<a href="' + wiki(sci) + '" target="_blank" rel="noopener">' + label + '</a>';
let shown = null; // the plate being looked at with the arrows; null = always the newest

function plates() {
  const s = state, items = [];
  const on = k => filter === 'all' || filter === k;
  if (on('birds')) s.birds.forEach(b => items.push({at: b.lastAt, kind: 'BIRD', key: b.sci, title: b.name, sci: b.sci, audio: b.audio,
    lines: [b.sci, day(b.lastAt) + ' ' + hhmm(b.lastAt) + ' · pewność ' + Math.round(b.conf * 100) + '%' + (b.count > 1 ? ' · ' + b.count + '×' : '')]}));
  if (on('planes')) s.planes.forEach(p => items.push({at: p.at, kind: 'PLANE', key: p.art, title: p.title,
    lines: [[p.airline, p.callsign].filter(Boolean).join(' · '), p.route, 'słychać było ' + day(p.at) + ' o ' + hhmm(p.at)]}));
  if (on('sounds')) s.sounds.forEach(e => items.push({at: e.at, kind: 'SCENE', key: e.art, title: e.label, audio: e.audio,
    lines: [e.title, e.subtitle, day(e.at) + ' ' + hhmm(e.at) + '–' + hhmm(e.lastAt)]}));
  items.forEach(i => i.id = i.kind + ':' + i.key + ':' + i.at);
  return items.sort((a, b) => b.at - a.at);
}

function renderPlate() {
  const list = plates();
  let i = shown ? list.findIndex(x => x.id === shown) : 0;
  if (i < 0) { i = 0; shown = null; }
  const n = list[i];
  if (!n) { $('#plate').innerHTML = '<p class="soft">Cisza.</p>'; return; }
  const go = j => '<button class="arrow" data-i="' + j + '"' + (j < 0 || j >= list.length ? ' disabled' : '') + '>';
  $('#plate').innerHTML =
    '<div class="nav">' + go(i + 1) + '‹ wcześniej</button><span class="soft">' + (i === 0 ? 'najnowsze' : (i + 1) + ' z ' + list.length +
      ' · <a href="#" data-now>wróć do najnowszego</a>') + '</span>' + go(i - 1) + 'później ›</button></div>' +
    art(n.kind, n.key, 'big') + '<div class="t">' + esc(n.title.charAt(0).toUpperCase() + n.title.slice(1)) + '</div>' +
    n.lines.filter(Boolean).map(l => '<div class="l">' + esc(l) + '</div>').join('') +
    (n.sci ? '<div class="l">' + (n.audio ? playBtn(n.audio) + ' ' : '') + wikiLink(n.sci, 'w Wikipedii ↗') + '</div>'
      : n.audio ? '<div class="l">' + playBtn(n.audio) + '</div>' : '');
  $('#plate').querySelectorAll('button[data-i]').forEach(b => b.onclick = () => { const j = +b.dataset.i; shown = j === 0 ? null : list[j].id; renderPlate(); });
  const now = $('#plate').querySelector('[data-now]');
  if (now) now.onclick = e => { e.preventDefault(); shown = null; renderPlate(); };
}

addEventListener('keydown', e => {
  if (!state || e.target.closest('input,textarea') || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight')) return;
  const b = $('#plate').querySelectorAll('button.arrow')[e.key === 'ArrowLeft' ? 0 : 1];
  if (b && !b.disabled) b.click();
});

function render() {
  const s = state;
  if (!s || !s.birds) { $('#plate').innerHTML = '<p class="soft">Jeszcze nic tu nie ma.</p>'; return; }
  $('#upd').textContent = 'aktualizacja ' + day(s.updatedAt) + ' ' + hhmm(s.updatedAt);
  renderPlate();

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
  // A recording for each: the species' best one if it may be public, else its newest public one.
  const bestOf = (s.stats && s.stats.birds.best) || {};
  const sound = sci => (bestOf[sci] && bestOf[sci].clip) || (s.birds.filter(b => b.sci === sci && b.audio).sort((a, b) => b.lastAt - a.lastAt)[0] || {}).audio;
  $('#top').innerHTML = top.map(t => '<li>' + art('BIRD', t.sci) + '<span style="flex:1">' + wikiLink(t.sci, esc(t.name)) +
    '<div class="bar" style="width:' + Math.max(4, 100 * t.n / max) + '%"></div></span><span class="soft">' + t.n + '×</span>' + playBtn(sound(t.sci)) + '</li>').join('') ||
    '<li class="soft">Jeszcze brak.</li>';

  // Chance and BirdNET confidence come from the add-on's history (longer than this page's 30-day journal).
  const st = s.stats, pct = p => Math.round(p * 100) + '%';
  const best = (st && st.birds.best) || {};
  const bestNote = sci => best[sci] ? '<div class="d">najlepsze nagranie: ' + pct(best[sci].conf) + ', ' + day(best[sci].at) + ' ' + playBtn(best[sci].clip) + '</div>' : '';
  const chanceRow = (c, v, note) => '<li>' + art('BIRD', c.sci) + '<span style="flex:1">' + wikiLink(c.sci, esc(c.name)) +
    (note ? '<div class="d">' + note + '</div>' : '') + bestNote(c.sci) + '<div class="bar" style="width:' + Math.max(4, v * 100) + '%"></div></span><span class="soft">' + pct(v) + '</span></li>';
  const confNote = c => c != null ? 'śr. pewność BirdNET ' + pct(c) : '';
  $('#chance').innerHTML = !st ? '' :
    '<h3 style="font-weight:400">Szansa usłyszenia teraz (' + st.hour + ':00–' + (st.hour + 1) + ':00)</h3>' +
    '<p class="soft">Na ilu z ' + st.daysObserved + ' ostatnich dni nasłuchu ptak odezwał się o tej godzinie.</p>' +
    '<ul class="top">' + (st.birds.chanceNow.map(c => chanceRow(c, c.now, confNote(c.conf))).join('') || '<li class="soft">O tej godzinie jeszcze nic.</li>') + '</ul>' +
    '<h3 style="font-weight:400">Szansa usłyszenia w ciągu dnia</h3><ul class="top">' +
    st.birds.chanceDay.slice(0, 16).map(c => chanceRow(c, c.day, 'najczęściej ok. ' + c.bestHour + ':00' + (c.conf != null ? ' · ' + confNote(c.conf) : ''))).join('') + '</ul>' +
    '<h3 style="font-weight:400">Średnia pewność BirdNET (30 dni)</h3><p class="soft">Jak bardzo model był pewny, że to ten gatunek, średnio ze wszystkich wykryć.</p><ul class="top">' +
    (st.birds.confidence || []).slice(0, 24).map(c => chanceRow(c, c.conf, c.count + ' wykryć')).join('') + '</ul>';
  const hours = Array(24).fill(0);
  b7.forEach(b => hours[new Date(b.lastAt).getHours()] += b.count);
  const hm = Math.max(1, ...hours);
  $('#hours').innerHTML = hours.map((v, h) => '<div title="' + h + ':00 · ' + v + '×" style="height:' + (100 * v / hm) + '%"></div>').join('');

  $('#filters').innerHTML = FILTERS.map(([k, l]) => '<button class="' + (k === filter ? 'on' : '') + '" data-f="' + k + '">' + l + '</button>').join('') +
    (state.animations && Object.keys(state.animations).length ? '<button id="pause" class="pause" onclick="togglePause()"></button>' : '');
  pauseLabel();
  $('#filters').querySelectorAll('button[data-f]').forEach(b => b.onclick = () => {
    filter = b.dataset.f; page = 0; shown = null;
    history.replaceState(null, '', location.pathname + (FILTERS.find(f => f[0] === filter)[2] ? '#' + FILTERS.find(f => f[0] === filter)[2] : ''));
    render();
  });
  const rows = [];
  if (filter === 'all' || filter === 'birds') s.birds.forEach(b => rows.push({at: b.lastAt, html: '<div class="row">' + art('BIRD', b.sci) +
    '<div>' + wikiLink(b.sci, esc(b.name.charAt(0).toUpperCase() + b.name.slice(1))) + '<div class="d">' + day(b.lastAt) + ' ' + hhmm(b.lastAt) + ' · ' + esc(b.sci) +
    ' · ' + Math.round(b.conf * 100) + '%' + (b.count > 1 ? ' · ' + b.count + '×' : '') + '</div></div>' + playBtn(b.audio) + '</div>'}));
  if (filter === 'all' || filter === 'planes') s.planes.forEach(p => rows.push({at: p.lastAt, html: '<div class="row">' + art('PLANE', p.art) +
    '<div>' + esc(p.title) + (p.callsign ? ' · ' + esc(p.callsign) : '') + '<div class="d">' +
    esc([day(p.at) + ' ' + hhmm(p.at), p.airline, p.route, p.altM ? p.altM + ' m' : ''].filter(Boolean).join(' · ')) + '</div></div></div>'}));
  if (filter === 'all' || filter === 'sounds') s.sounds.forEach(e => rows.push({at: e.lastAt, html: '<div class="row">' + art('SCENE', e.art) +
    '<div>' + esc(e.label) + (e.title ? ': ' + esc(e.title) : '') + '<div class="d">' + day(e.at) + ' ' + hhmm(e.at) + '–' + hhmm(e.lastAt) +
    (e.subtitle ? ' · ' + esc(e.subtitle) : '') + '</div></div>' + playBtn(e.audio) + '</div>'}));
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
