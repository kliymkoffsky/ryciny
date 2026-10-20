'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const workerSource = fs.readFileSync(path.join(__dirname, 'worker.js'), 'utf8');

function inlineSource() {
  /*
   * Evaluate the real PAGE template first so tests see the same escaped
   * inline script that a browser receives from the Worker.
   */

  const marker = 'const PAGE = `';
  const start = workerSource.indexOf(marker);
  const end = workerSource.lastIndexOf('`;');
  const page = vm.runInNewContext(workerSource.slice(start, end + 2) + '\nPAGE');
  const scriptStart = page.indexOf('<script>') + '<script>\n'.length;
  const scriptEnd = page.indexOf('\n</script>', scriptStart);
  return page.slice(scriptStart, scriptEnd);
}

function classListFor(owner) {
  return {
    add(...names) { names.forEach(name => owner._classes.add(name)); },
    remove(...names) { names.forEach(name => owner._classes.delete(name)); },
    toggle(name, force) {
      const next = force === undefined ? !owner._classes.has(name) : force;
      if (next) owner._classes.add(name); else owner._classes.delete(name);
      return next;
    },
    contains(name) { return owner._classes.has(name); },
  };
}

function createRuntime({ savedPause = null, reducedMotion = false, spriteLoads = true, rejectPlay = false } = {}) {
  /*
   * Provide only the browser surface exercised by the viewer state machine.
   * The fetch promise stays pending so startup rendering cannot obscure the
   * focused lifecycle assertions below.
   */

  const windowListeners = new Map();
  const documentListeners = new Map();
  const audioInstances = [];
  const rows = [];
  const ids = new Map();

  class FakeElement {
    constructor(tagName = 'div', classes = '') {
      this.tagName = tagName.toUpperCase();
      this._classes = new Set(classes.split(/\s+/).filter(Boolean));
      this.classList = classListFor(this);
      this.dataset = {};
      this.style = {};
      this.attributes = new Map();
      this.children = [];
      this.parentNode = null;
      this.isConnected = true;
      this.textContent = '';
      this._styleText = '';
      this._outerHTML = '';
    }

    get className() { return [...this._classes].join(' '); }
    set className(value) { this._classes = new Set(String(value).split(/\s+/).filter(Boolean)); }
    setAttribute(name, value) {
      const text = String(value);
      this.attributes.set(name, text);
      if (name === 'class') this.className = text;
      if (name === 'style') this._styleText = text;
    }
    getAttribute(name) {
      if (name === 'class') return this.className;
      if (name === 'style') return this._styleText;
      return this.attributes.get(name) ?? null;
    }
    closest(selector) { return selector === '.top li, .row' ? this._row || null : null; }
    contains(node) {
      return node === this || this.children.some(child => child === node || child.contains(node));
    }
    querySelector(selector) {
      if (selector === 'img[data-anim]') return this.children.find(child => child.tagName === 'IMG' && child.dataset.anim) || null;
      if (selector === '.anim[data-anim]') return this.children.find(child => child.classList.contains('anim') && child.dataset.anim) || null;
      return null;
    }
    querySelectorAll() { return []; }
    replaceWith(node) {
      if (this.parentNode) this.parentNode.replaceChild(this, node);
    }
    get outerHTML() {
      if (this._outerHTML) return this._outerHTML;
      return '<' + this.tagName.toLowerCase() + ' class="' + this.className + '"></' + this.tagName.toLowerCase() + '>';
    }
    set outerHTML(value) {
      this._outerHTML = String(value);
      if (this.parentNode) this.parentNode.replaceChild(this, fallbackImage(this.dataset.anim));
    }
  }

  function fallbackImage(id) {
    const image = new FakeElement('img', 'still thumb');
    image.dataset.anim = id;
    image.dataset.animMode = 'row';
    image.setAttribute('alt', '');
    image.setAttribute('style', 'width:58px;height:58px');
    return image;
  }

  class FakeRow extends FakeElement {
    constructor() {
      super('li', 'top');
      this._row = this;
    }
    appendChild(child) {
      child.parentNode = this;
      child.isConnected = this.isConnected;
      child._row = this;
      this.children.push(child);
      return child;
    }
    replaceChild(oldChild, newChild) {
      const index = this.children.indexOf(oldChild);
      if (index < 0) return;
      oldChild.isConnected = false;
      newChild.parentNode = this;
      newChild.isConnected = this.isConnected;
      newChild._row = this;
      this.children[index] = newChild;
    }
  }

  class FakeAudio {
    constructor(url) {
      this.url = url;
      this.paused = true;
      this.currentTime = 0;
      this.playCalls = 0;
      this.pauseCalls = 0;
      audioInstances.push(this);
    }
    play() {
      this.playCalls += 1;
      this.paused = false;
      return rejectPlay ? Promise.reject(new Error('autoplay rejected')) : Promise.resolve();
    }
    pause() {
      this.paused = true;
      this.pauseCalls += 1;
      if (this.onpause) this.onpause({type: 'pause', target: this});
    }
    emit(type) {
      if (type === 'playing') this.paused = false;
      if (type === 'pause') this.paused = true;
      const callback = this['on' + type];
      if (callback) callback({type, target: this});
    }
  }

  class FakeImage {
    set src(value) {
      this._src = value;
      queueMicrotask(() => {
        if (spriteLoads) { if (this.onload) this.onload(); }
        else if (this.onerror) this.onerror(new Error('missing sprite'));
      });
    }
    get src() { return this._src; }
  }

  ids.set('upd', new FakeElement('span'));
  ids.set('pause', new FakeElement('button', 'pause'));
  ids.set('animNote', new FakeElement('p'));
  const document = {
    hidden: false,
    documentElement: {contains: node => !!node && node.isConnected !== false},
    querySelector(selector) { return selector.startsWith('#') ? ids.get(selector.slice(1)) || null : null; },
    querySelectorAll(selector) { return selector === '.top li, .row' ? rows : []; },
    getElementById(id) { return ids.get(id) || null; },
    createElement(tagName) { return new FakeElement(tagName); },
    addEventListener(type, callback) { documentListeners.set(type, callback); },
  };
  const media = {matches: reducedMotion, addEventListener(type, callback) { this._change = callback; }};
  const context = {
    __RYCINY_TEST__: true,
    document,
    localStorage: {getItem: () => savedPause, setItem() {}},
    matchMedia: () => media,
    Image: FakeImage,
    Audio: FakeAudio,
    fetch: () => new Promise(() => {}),
    setInterval() {},
    addEventListener(type, callback) { windowListeners.set(type, callback); },
    queueMicrotask,
    location: {hash: '', pathname: '/'},
    history: {replaceState() {}},
    console,
  };
  vm.runInNewContext(inlineSource(), context, {filename: 'public-site/worker.inline.js'});
  return {
    viewer: context.__rycinyViewerTest,
    audioInstances,
    document,
    makeRow(id) {
      const row = new FakeRow();
      const image = fallbackImage(id);
      image.outerHTML = '<img class="still thumb" data-anim="' + id + '" data-anim-mode="row">';
      row.appendChild(image);
      rows.push(row);
      return row;
    },
    makeButton(name, row) {
      const button = new FakeElement('button', 'play');
      button.dataset.n = name;
      button._row = row;
      button.textContent = '▶';
      return button;
    },
    media,
    windowListeners,
    documentListeners,
  };
}

async function flush() {
  await new Promise(resolve => setImmediate(resolve));
}

test('animation preference is enabled by default and honors explicit saved pause', () => {
  assert.equal(createRuntime().viewer.getPaused(), false);
  assert.equal(createRuntime({savedPause: '0'}).viewer.getPaused(), false);
  assert.equal(createRuntime({savedPause: '1'}).viewer.getPaused(), true);
});

test('state loading keeps only valid animation descriptors and clip names', () => {
  const id = 'a'.repeat(64);
  const runtime = createRuntime();
  const state = runtime.viewer.normalizeState({
    birds: [{audio: '01234567.wav'}, {audio: 'abcdef12xmp3'}, {audio: 'not-a-clip.wav'}, {audio: 12}],
    animations: {
      'BIRD:good': {id, w: 64, h: 64},
      'BIRD:bad-id': {id: 'bad', w: 64, h: 64},
      'BIRD:bad-size': {id, w: '64', h: 64},
      'INVALID:kind': {id, w: 64, h: 64},
    },
    stats: {birds: {best: {Turdus: {clip: '89abcdef.mp3'}, Corvus: {clip: 'bad'}}}},
  });
  assert.equal(state.birds[0].audio, '01234567.wav');
  assert.equal(state.birds[1].audio, null);
  assert.equal(state.birds[2].audio, null);
  assert.equal(state.birds[3].audio, null);
  assert.deepEqual(Object.keys(state.animations), ['BIRD:good']);
  assert.equal(state.stats.birds.best.Turdus.clip, '89abcdef.mp3');
  assert.equal(state.stats.birds.best.Corvus.clip, null);
});

test('row animation follows actual playing, pause, resume, and ended events', async () => {
  const id = 'b'.repeat(64);
  const runtime = createRuntime();
  const row = runtime.makeRow(id);
  const button = runtime.makeButton('01234567.wav', row);

  runtime.viewer.play(button);
  const audio = runtime.viewer.getPlayer();
  assert.ok(audio);
  assert.equal(button.textContent, '▶');
  assert.equal(runtime.viewer.isAudioRowActive(row), false);

  audio.emit('playing');
  await flush();
  assert.equal(button.textContent, '❚❚');
  assert.equal(runtime.viewer.isAudioRowActive(row), true);
  assert.ok(row.querySelector('.anim[data-anim]'));

  runtime.viewer.play(button);
  assert.equal(runtime.viewer.getPlayer(), audio);
  assert.equal(audio.playCalls, 1);
  assert.equal(runtime.viewer.isAudioRowActive(row), false);
  assert.equal(button.textContent, '▶');

  runtime.viewer.play(button);
  assert.equal(runtime.viewer.getPlayer(), audio);
  assert.equal(audio.playCalls, 2);
  audio.emit('playing');
  await flush();
  audio.emit('ended');
  assert.equal(runtime.viewer.getPlayer(), null);
  assert.equal(runtime.viewer.isAudioRowActive(row), false);
  assert.equal(button.textContent, '▶');
});

test('reduced motion and hidden visibility suppress sprites until policy clears', async () => {
  const reduced = createRuntime({reducedMotion: true});
  const reducedRow = reduced.makeRow('e'.repeat(64));
  const reducedButton = reduced.makeButton('01234567.wav', reducedRow);
  reduced.viewer.play(reducedButton);
  const reducedAudio = reduced.viewer.getPlayer();
  reducedAudio.emit('playing');
  await flush();
  assert.equal(reduced.viewer.isAudioRowActive(reducedRow), true);
  assert.equal(reducedRow.querySelector('.anim[data-anim]'), null);

  reduced.media.matches = false;
  reduced.media._change({matches: false});
  await flush();
  assert.ok(reducedRow.querySelector('.anim[data-anim]'));

  const hidden = createRuntime();
  const hiddenRow = hidden.makeRow('f'.repeat(64));
  const hiddenButton = hidden.makeButton('89abcdef.mp3', hiddenRow);
  hidden.document.hidden = true;
  hidden.viewer.play(hiddenButton);
  const hiddenAudio = hidden.viewer.getPlayer();
  hiddenAudio.emit('playing');
  await flush();
  assert.equal(hidden.viewer.isAudioRowActive(hiddenRow), true);
  assert.equal(hiddenRow.querySelector('.anim[data-anim]'), null);

  hidden.document.hidden = false;
  hidden.windowListeners.get('visibilitychange')();
  await flush();
  assert.ok(hiddenRow.querySelector('.anim[data-anim]'));
});

test('switching clips ignores stale media events from the disposed player', async () => {
  const runtime = createRuntime();
  const firstRow = runtime.makeRow('1'.repeat(64));
  const secondRow = runtime.makeRow('2'.repeat(64));
  const firstButton = runtime.makeButton('01234567.wav', firstRow);
  const secondButton = runtime.makeButton('89abcdef.mp3', secondRow);

  runtime.viewer.play(firstButton);
  const firstAudio = runtime.viewer.getPlayer();
  firstAudio.emit('playing');
  await flush();
  assert.equal(runtime.viewer.isAudioRowActive(firstRow), true);

  runtime.viewer.play(secondButton);
  const secondAudio = runtime.viewer.getPlayer();
  assert.notEqual(secondAudio, firstAudio);
  assert.equal(runtime.viewer.isAudioRowActive(firstRow), false);
  assert.equal(runtime.viewer.isAudioRowActive(secondRow), false);

  firstAudio.emit('playing');
  firstAudio.emit('error');
  await flush();
  assert.equal(runtime.viewer.getPlayer(), secondAudio);
  assert.equal(runtime.viewer.isAudioRowActive(firstRow), false);

  secondAudio.emit('playing');
  await flush();
  assert.equal(runtime.viewer.isAudioRowActive(secondRow), true);
});

test('rejected playback and missing sprites leave no stale demand or blank fallback', async () => {
  const rejected = createRuntime({rejectPlay: true});
  const row = rejected.makeRow('c'.repeat(64));
  const button = rejected.makeButton('01234567.wav', row);
  rejected.viewer.play(button);
  await flush();
  assert.equal(rejected.viewer.getPlayer(), null);
  assert.equal(rejected.viewer.isAudioRowActive(row), false);
  assert.equal(button.textContent, '▶');

  const missing = createRuntime({spriteLoads: false});
  const missingRow = missing.makeRow('d'.repeat(64));
  const missingButton = missing.makeButton('89abcdef.mp3', missingRow);
  missing.viewer.play(missingButton);
  const audio = missing.viewer.getPlayer();
  audio.emit('playing');
  await flush();
  assert.equal(missing.viewer.isAudioRowActive(missingRow), true);
  assert.ok(missingRow.querySelector('img[data-anim]'));
  audio.emit('error');
  assert.equal(missing.viewer.getPlayer(), null);
  assert.equal(missing.viewer.isAudioRowActive(missingRow), false);
});
