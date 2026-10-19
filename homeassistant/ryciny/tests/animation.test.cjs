const assert = require('node:assert/strict');
const test = require('node:test');

const {Manager, Player, normalizeDescriptor} = require('../app/ryciny/web/animation.js');

class Element {
  constructor(documentRef) {
    this.ownerDocument = documentRef;
    this.children = [];
    this.hidden = false;
    this.isConnected = true;
    this.style = {setProperty: (key, value) => { this.style[key] = value; }};
    this.listeners = {};
    this.attributes = {};
    this.classList = {values: new Set(), add: value => this.classList.values.add(value), remove: value => this.classList.values.delete(value), contains: value => this.classList.values.has(value)};
  }

  appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
  replaceChildren(...children) { this.children = []; children.forEach(child => this.appendChild(child)); }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  removeEventListener(type, listener) { if (this.listeners[type] === listener) delete this.listeners[type]; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
}

class Document extends Element {
  constructor() { super(null); this.nodeType = 9; this.hidden = false; }
  createElement(tag) {
    const image = new Element(this);
    if (tag === 'img') Object.defineProperty(image, 'src', {
      get: () => image._src || '',
      set: value => { image._src = value; queueMicrotask(() => image.onload?.()); },
    });
    return image;
  }
}

function descriptor(id = 'plate-1', subject = ['BIRD', 'blackbird']) {
  return {id, subject, width: 100, height: 120, frameMs: 180,
    atlas: 'api/animations/plate-1.png', placement: [10, 20, 80, 90]};
}

function harness({enabled = true, autoPlay = true, subject, fetchImpl, media} = {}) {
  const documentRef = new Document();
  const container = new Element(documentRef);
  const staticImage = new Element(documentRef);
  const toggle = new Element(documentRef);
  staticImage.src = 'api/plate.png';
  const previousFetch = global.fetch;
  const previousMatchMedia = global.matchMedia;
  global.fetch = fetchImpl || (async () => ({ok: true, json: async () => descriptor()}));
  global.matchMedia = () => media || {matches: false};
  const player = new Player({container, staticImage, toggle, enabled, autoPlay, expectedSubject: subject,
    endpoint: 'api/plate-animation?w=100&h=120'});
  return {player, container, staticImage, toggle, restore: () => { global.fetch = previousFetch; global.matchMedia = previousMatchMedia; }};
}

test('normalizes the atlas contract and derives the 900ms six-pose cycle', () => {
  const normalized = normalizeDescriptor(descriptor());
  assert.equal(normalized.atlas, 'api/animations/plate-1.png');
  assert.equal(normalized.frameMs, 180);
  assert.deepEqual(normalized.placement, [10, 20, 80, 90]);
  assert.throws(() => normalizeDescriptor({...descriptor(), atlas: '../atlas.png'}), /relative/);
  assert.throws(() => normalizeDescriptor({...descriptor(), subject: ['BIRD']}), /id and subject/);
});

test('preloads and keeps a manual stop through descriptor refresh', async () => {
  let payload = descriptor('caption-1');
  const h = harness({fetchImpl: async () => ({ok: true, json: async () => payload})});
  await h.player.refresh();
  assert.equal(h.player.sprite.classList.contains('is-playing'), true);
  assert.equal(h.player.track.style['--animation-duration'], '900ms');
  h.player.stop(true);
  h.player.setVisible(false);
  assert.equal(h.staticImage.hidden, false);
  h.player.setVisible(true);
  assert.equal(h.container.hidden, false);
  payload = descriptor('new-subject', ['PLANE', 'E75S-LOT']);
  await h.player.refresh();
  assert.equal(h.player.sprite.classList.contains('is-playing'), false);
  assert.equal(h.player.stopped, true);
  assert.equal(h.container.hidden, false);
  h.player.play();
  assert.equal(h.player.sprite.classList.contains('is-playing'), true);
  h.player.dispose();
  h.restore();
});

test('microphone audio without an art binding does not demand animation', () => {
  const documentRef = new Document();
  const manager = new Manager({root: documentRef, enabled: false});
  assert.equal(manager.demand(null), false);
  manager.dispose();
});

test('reduced motion and disabled playback keep the untouched fallback', async () => {
  const reduced = harness();
  global.matchMedia = () => ({matches: true});
  await reduced.player.refresh();
  assert.equal(reduced.player.ready, false);
  assert.equal(reduced.staticImage.src, 'api/plate.png');
  const disabled = harness({enabled: false});
  await disabled.player.refresh();
  assert.equal(disabled.player.ready, false);
  assert.equal(disabled.container.hidden, true);
  reduced.player.dispose();
  disabled.player.dispose();
  reduced.restore();
  disabled.restore();
});

test('live reduced-motion changes freeze the ready player and hide replay', async () => {
  const media = {matches: false, listeners: [], addEventListener: (_, listener) => media.listeners.push(listener), removeEventListener: () => {}};
  const h = harness({media});
  await h.player.refresh();
  media.matches = true;
  media.listeners[0]();
  assert.equal(h.player.toggle?.hidden, true);
  assert.equal(h.player.track.style.transform, 'translateX(0)');
  media.matches = false;
  media.listeners[0]();
  assert.equal(h.player.sprite.classList.contains('is-playing'), true);
  h.player.dispose();
  h.restore();
});

test('stale descriptor work cannot activate a disposed player', async () => {
  let resolve;
  const h = harness({fetchImpl: async () => new Promise(result => { resolve = result; })});
  const refresh = h.player.refresh();
  h.player.dispose();
  resolve({ok: true, json: async () => descriptor()});
  await refresh;
  assert.equal(h.player.ready, false);
  assert.equal(h.staticImage.src, 'api/plate.png');
  h.restore();
});
