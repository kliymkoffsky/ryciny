(function (root) {
  'use strict';

  const FRAME_COUNT = 6;
  const FRAME_MS = 180;
  const PLAYBACK_RATE = 1.2;

  function sameSubject(left, right) {
    return Array.isArray(left) && Array.isArray(right) && left.length === 2 && right.length === 2 &&
      left[0] === right[0] && left[1] === right[1];
  }

  function relativeUrl(value, field) {
    if (typeof value !== 'string' || !value || value.startsWith('/') || value.startsWith('\\') ||
        value.includes('..') || value.includes('\\') || value.includes('//') ||
        /^[a-z][a-z\d+.-]*:/i.test(value) || /[\u0000-\u0020\u007f]/.test(value)) {
      throw new TypeError(`${field} must be a relative URL`);
    }
    return value;
  }

  function normalizeDescriptor(payload) {
    /*
     * Validate the one server descriptor before a request can replace the
     * ordinary still. The atlas contains six equal-width poses.
     */

    if (payload == null) return null;
    if (typeof payload !== 'object' || Array.isArray(payload) || typeof payload.id !== 'string' || !payload.id ||
        !Array.isArray(payload.subject) || payload.subject.length !== 2 || payload.subject.some(value => typeof value !== 'string' || !value)) {
      throw new TypeError('animation descriptor must contain an id and subject');
    }
    const width = Number(payload.width);
    const height = Number(payload.height);
    const frameMs = Number(payload.frameMs);
    if (!Number.isInteger(width) || width < 1 || !Number.isInteger(height) || height < 1 ||
        frameMs !== FRAME_MS) {
      throw new TypeError('animation descriptor must contain valid dimensions and frameMs');
    }
    const atlas = relativeUrl(payload.atlas, 'atlas');
    const rawPlacement = payload.placement == null ? [0, 0, width, height] : payload.placement;
    if (!Array.isArray(rawPlacement) || rawPlacement.length !== 4 ||
        rawPlacement.some(value => !Number.isFinite(Number(value)) || Number(value) < 0)) {
      throw new TypeError('placement must be a four-number array');
    }
    const placement = rawPlacement.map(Number);
    if (placement[2] <= 0 || placement[3] <= 0 || placement[0] + placement[2] > width ||
        placement[1] + placement[3] > height) {
      throw new TypeError('placement must fit inside the frame canvas');
    }
    if (payload.background != null &&
        (typeof payload.background !== 'string' || !payload.background.startsWith('data:image/'))) {
      throw new TypeError('background must be a data image');
    }
    return {id: payload.id, subject: [payload.subject[0], payload.subject[1]], width, height, frameMs,
      atlas, background: payload.background || null, placement};
  }

  class Player {
    constructor(options = {}) {
      /*
       * Main and thumbnail playback share this renderer. Epoch checks keep
       * late descriptor or image work from mounting after a route change.
       */

      this.container = options.container;
      this.staticImage = options.staticImage || null;
      this.toggle = options.toggle || null;
      this.endpoint = options.endpoint || '';
      this.documentRef = this.container?.ownerDocument || root.document;
      this.expectedSubject = options.expectedSubject || null;
      this.frameFit = options.frameFit || 'fill';
      this.enabled = options.enabled !== false;
      this.autoPlay = options.autoPlay === true;
      this.active = options.active !== false;
      this.visible = !this.documentRef?.hidden;
      this.stopped = false;
      this.ready = false;
      this.disposed = false;
      this.epoch = 0;
      this.descriptor = null;
      this.sprite = null;
      this.track = null;
      this.visibility = () => this.setVisible(!this.documentRef.hidden);
      this.motionQuery = root.matchMedia?.('(prefers-reduced-motion: reduce)') || null;
      this.motionChanged = () => {
        this.syncPlayback();
        this.updateToggle();
      };
      this.toggleClick = () => this.sprite?.classList.contains('is-playing') ? this.stop(true) : this.play({manual: true});
      this.documentRef?.addEventListener?.('visibilitychange', this.visibility);
      this.motionQuery?.addEventListener?.('change', this.motionChanged);
      this.toggle?.addEventListener?.('click', this.toggleClick);
      this.show();
      this.updateToggle();
    }

    reducedMotion() {
      return Boolean(root.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
    }

    updateToggle() {
      if (!this.toggle) return;
      const playing = this.sprite?.classList.contains('is-playing');
      this.toggle.hidden = !this.ready || !this.enabled || this.reducedMotion();
      this.toggle.textContent = playing ? 'Zatrzymaj animację' : 'Odtwórz animację';
      this.toggle.setAttribute?.('aria-pressed', playing ? 'true' : 'false');
    }

    show(mode = 'static') {
      if (mode !== 'static' && (!this.ready || !this.sprite)) mode = 'static';
      this.sprite?.classList.remove('is-playing');
      if (mode === 'frame' && this.track) this.track.style.transform = 'translateX(0)';
      if (this.container) {
        this.container.hidden = mode === 'static';
        this.container.setAttribute?.('aria-hidden', String(mode === 'static'));
      }
      if (this.staticImage) this.staticImage.hidden = mode !== 'static';
    }

    syncPlayback() {
      if (!this.autoPlay || !this.enabled || !this.active || !this.visible) return this.show();
      if (this.stopped || this.reducedMotion()) return this.show('frame');
      if (this.ready) return this.play({manual: false});
      this.refresh();
    }

    loadImage(url) {
      const image = this.documentRef?.createElement?.('img');
      if (!image) return Promise.reject(new Error('Image is unavailable'));
      image.decoding = 'async';
      return new Promise((resolve, reject) => {
        image.onload = () => {
          try { Promise.resolve(image.decode?.()).then(() => resolve(image), reject); }
          catch (error) { reject(error); }
        };
        image.onerror = () => reject(new Error(`Unable to load animation asset: ${url}`));
        image.src = url;
      });
    }

    mount(descriptor, atlas, background) {
      const [x, y, width, height] = descriptor.placement;
      const sprite = this.documentRef.createElement('span');
      sprite.className = 'animation-sprite';
      Object.assign(sprite.style, {position: 'absolute', overflow: 'hidden'});
      if (this.frameFit === 'contain') {
        const ratio = descriptor.width / descriptor.height;
        if (ratio >= 1) Object.assign(sprite.style, {left: '0', width: '100%', top: `${(1 - 1 / ratio) * 50}%`, height: `${100 / ratio}%`});
        else Object.assign(sprite.style, {left: `${(1 - ratio) * 50}%`, width: `${ratio * 100}%`, top: '0', height: '100%'});
      } else {
        Object.assign(sprite.style, {left: `${x * 100 / descriptor.width}%`, top: `${y * 100 / descriptor.height}%`,
          width: `${width * 100 / descriptor.width}%`, height: `${height * 100 / descriptor.height}%`});
      }
      atlas.className = 'animation-sprite__track';
      atlas.alt = '';
      atlas.draggable = false;
      Object.assign(atlas.style, {position: 'absolute', left: '0', top: '0', width: '600%', height: '100%',
        maxWidth: 'none', display: 'block', objectFit: 'fill', transform: 'translateX(0)'});
      atlas.style.setProperty('--animation-duration', `${descriptor.frameMs * FRAME_COUNT / PLAYBACK_RATE}ms`);
      sprite.appendChild(atlas);
      if (background) {
        background.className = 'animation-background';
        background.alt = '';
        background.draggable = false;
        Object.assign(background.style, {position: 'absolute', inset: '0', width: '100%', height: '100%', display: 'block'});
      }
      this.container.replaceChildren(...(background ? [background, sprite] : [sprite]));
      this.container.style.position = 'absolute';
      this.sprite = sprite;
      this.track = atlas;
    }

    async refresh() {
      if (this.disposed) return null;
      const epoch = ++this.epoch;
      this.show();
      this.updateToggle();
      if (!this.enabled || this.reducedMotion() || typeof root.fetch !== 'function') return this.fallback();
      try {
        const response = await root.fetch(this.endpoint, {cache: 'no-store'});
        if (!response?.ok) throw new Error('animation request failed');
        const descriptor = normalizeDescriptor(await response.json());
        if (epoch !== this.epoch || this.disposed || this.container?.isConnected === false) return null;
        if (!descriptor) return this.fallback();
        if (this.expectedSubject && !sameSubject(this.expectedSubject, descriptor.subject)) throw new Error('animation subject mismatch');
        const [atlas, background] = await Promise.all([this.loadImage(descriptor.atlas),
          descriptor.background ? this.loadImage(descriptor.background) : Promise.resolve(null)]);
        if (epoch !== this.epoch || this.disposed || this.container?.isConnected === false || !this.enabled) return null;
        this.mount(descriptor, atlas, background);
        this.ready = true;
        this.syncPlayback();
        this.updateToggle();
        return descriptor;
      } catch (_) {
        if (epoch === this.epoch && !this.disposed) this.fallback();
        return null;
      }
    }

    fallback() {
      this.ready = false;
      this.sprite = null;
      this.track = null;
      this.container?.replaceChildren?.();
      this.show();
      this.updateToggle();
      return null;
    }

    play({manual = true} = {}) {
      if (this.disposed || !this.enabled || !this.ready || !this.active || !this.visible || this.reducedMotion()) return false;
      if (manual) this.stopped = false;
      this.show('animation');
      this.track.style.transform = '';
      this.sprite.classList.add('is-playing');
      this.updateToggle();
      return true;
    }

    stop(manual = true) {
      if (manual) this.stopped = true;
      if (manual) this.syncPlayback();
      else this.show();
      this.updateToggle();
    }

    setActive(active) {
      this.active = Boolean(active);
      this.syncPlayback();
      this.updateToggle();
    }

    setEnabled(enabled) {
      this.enabled = Boolean(enabled);
      this.epoch += 1;
      if (!this.enabled) this.fallback();
      else this.syncPlayback();
      this.updateToggle();
    }

    setVisible(visible) {
      this.visible = Boolean(visible);
      this.syncPlayback();
      this.updateToggle();
    }

    dispose() {
      if (this.disposed) return;
      this.disposed = true;
      this.epoch += 1;
      this.documentRef?.removeEventListener?.('visibilitychange', this.visibility);
      this.motionQuery?.removeEventListener?.('change', this.motionChanged);
      this.toggle?.removeEventListener?.('click', this.toggleClick);
      this.fallback();
    }
  }

  class Manager {
    constructor(options = {}) {
      /*
       * Refresh only the route whose rows changed. This keeps journal players
       * alive when statistics render and vice versa without a DOM observer.
       */

      this.root = options.root || root.document;
      this.documentRef = this.root?.nodeType === 9 ? this.root : this.root?.ownerDocument || root.document;
      this.enabled = options.enabled !== false;
      this.active = options.active !== false;
      this.bindings = [];
      this.audio = null;
      this.click = event => this.handleClick(event);
      this.visibility = () => {
        if (!this.documentRef.hidden) this.bindings.filter(binding => this.demand(binding)).forEach(binding => this.start(binding));
      };
      this.motionQuery = root.matchMedia?.('(prefers-reduced-motion: reduce)') || null;
      this.motionChanged = () => {
        this.bindings.filter(binding => this.demand(binding)).forEach(binding => {
          if (this.motionQuery?.matches) binding.player.show('frame');
          else this.start(binding);
        });
      };
      this.root?.addEventListener?.('click', this.click);
      this.documentRef?.addEventListener?.('visibilitychange', this.visibility);
      this.motionQuery?.addEventListener?.('change', this.motionChanged);
    }

    demand(binding) {
      return Boolean(binding && (binding.hovered || (this.audio?.binding === binding && this.audio.playing)));
    }

    refresh(scope) {
      if (!scope) return [];
      this.bindings = this.bindings.filter(binding => {
        if (binding.wrapper.isConnected === false || scope.contains?.(binding.wrapper)) {
          binding.wrapper.removeEventListener('mouseenter', binding.enter);
          binding.wrapper.removeEventListener('mouseleave', binding.leave);
          binding.player.dispose();
          return false;
        }
        return true;
      });
      if (!this.enabled) return this.bindings;
      Array.from(scope.querySelectorAll?.('.element-art') || []).forEach(wrapper => {
        const still = wrapper.querySelector?.('.element-art__still');
        const motion = wrapper.querySelector?.('.element-art__motion');
        const kind = wrapper.dataset?.animationKind || wrapper.getAttribute?.('data-animation-kind');
        const key = wrapper.dataset?.animationKey || wrapper.getAttribute?.('data-animation-key');
        if (!still || !motion || !kind || !key) return;
        const player = new Player({container: motion, staticImage: still,
          endpoint: `api/animation?kind=${encodeURIComponent(kind)}&key=${encodeURIComponent(key)}`,
          expectedSubject: [kind, key], active: this.active, enabled: this.enabled, frameFit: 'contain'});
        const binding = {wrapper, player, hovered: false};
        binding.enter = () => { binding.hovered = true; this.start(binding); };
        binding.leave = () => { binding.hovered = false; if (!this.demand(binding)) player.stop(false); };
        wrapper.addEventListener('mouseenter', binding.enter);
        wrapper.addEventListener('mouseleave', binding.leave);
        this.bindings.push(binding);
      });
      return this.bindings;
    }

    start(binding) {
      if (!this.demand(binding) || !this.active || !this.enabled) return;
      if (binding.player.ready) binding.player.play({manual: false});
      else binding.player.refresh().then(() => { if (this.demand(binding)) binding.player.play({manual: false}); });
    }

    setActive(active) {
      this.active = Boolean(active);
      this.bindings.forEach(binding => binding.player.setActive(this.active));
    }

    setEnabled(enabled) {
      this.enabled = Boolean(enabled);
      this.bindings.forEach(binding => binding.player.setEnabled(this.enabled));
    }

    stopAll() {
      if (this.audio) this.finishAudio(this.audio, true);
      this.bindings.forEach(binding => binding.player.stop(false));
    }

    buttonState(record, playing) {
      record.button.textContent = `${playing ? '■' : '▶'}${record.suffix}`;
      record.button.setAttribute?.('aria-pressed', playing ? 'true' : 'false');
    }

    finishAudio(record, discard = false) {
      if (!record) return;
      record.listeners.forEach(([type, listener]) => record.audio.removeEventListener(type, listener));
      if (discard) record.audio.pause?.();
      if (!record.binding?.hovered) record.binding?.player.stop(false);
      record.playing = false;
      this.buttonState(record, false);
      if (this.audio === record) this.audio = null;
    }

    toggleAudio(button, source, binding) {
      if (this.audio?.button === button) {
        if (this.audio.playing || this.audio.audio.paused === false) this.finishAudio(this.audio, true);
        else this.startAudio(this.audio);
        return;
      }
      if (this.audio) this.finishAudio(this.audio, true);
      let audio;
      try { audio = new root.Audio(source); } catch (_) { return; }
      const record = {button, binding, audio, playing: false, suffix: String(button.textContent || '').replace(/^[▶■]\s*/, ''), listeners: []};
      this.audio = record;
      const playing = () => { record.playing = true; this.buttonState(record, true); if (binding) this.start(binding); };
      const paused = () => { record.playing = false; this.buttonState(record, false); if (!this.demand(binding)) binding?.player.stop(false); };
      const ended = () => this.finishAudio(record);
      record.listeners = [['playing', playing], ['pause', paused], ['ended', ended], ['error', ended]];
      record.listeners.forEach(([type, listener]) => audio.addEventListener(type, listener));
      this.buttonState(record, false);
      this.startAudio(record);
    }

    startAudio(record) {
      try {
        const result = record.audio.play();
        result?.catch?.(() => this.finishAudio(record, true));
      } catch (_) {
        this.finishAudio(record, true);
      }
    }

    handleClick(event) {
      const button = event?.target?.closest?.('[data-audio-src]');
      const source = button?.dataset?.audioSrc || button?.getAttribute?.('data-audio-src') || '';
      if (!/^(?:api\/(?:clips|best)\/[0-9a-f]{8}\.(?:wav|mp3)|api\/mic\.wav(?:\?t=\d+)?)$/i.test(source)) return;
      const wrapper = button?.closest?.('.row')?.querySelector?.('.element-art');
      const binding = this.bindings.find(item => item.wrapper === wrapper) || null;
      event.preventDefault?.();
      this.toggleAudio(button, source, binding);
    }

    dispose() {
      this.stopAll();
      this.bindings.forEach(binding => {
        binding.wrapper.removeEventListener('mouseenter', binding.enter);
        binding.wrapper.removeEventListener('mouseleave', binding.leave);
        binding.player.dispose();
      });
      this.bindings = [];
      this.root?.removeEventListener?.('click', this.click);
      this.documentRef?.removeEventListener?.('visibilitychange', this.visibility);
      this.motionQuery?.removeEventListener?.('change', this.motionChanged);
    }
  }

  const api = {Manager, Player, normalizeDescriptor, FRAME_COUNT, FRAME_MS};
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.RycinyAnimation = api;
})(typeof globalThis === 'object' ? globalThis : this);
