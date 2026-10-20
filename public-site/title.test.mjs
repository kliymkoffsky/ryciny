import assert from 'node:assert/strict';
import {test} from 'node:test';
import vm from 'node:vm';
import worker from './worker.js';

async function titleRenderer() {
  const response = await worker.fetch(new Request('https://example.test/'), {}, {});
  const html = await response.text();
  assert.match(html, /<h1 id="stationTitle">Dźwięki Dolnego Migowa<\/h1>/);
  const script = html.match(/function renderStationTitle\(value\) \{[\s\S]*?\n\}\n\nasync function load/)[0]
    .replace(/\n\nasync function load$/, '');
  const heading = {textContent: '', set innerHTML(_) { throw new Error('Title must never use innerHTML'); }};
  const document = {title: ''};
  const context = vm.createContext({document, $: selector => { assert.equal(selector, '#stationTitle'); return heading; }});
  vm.runInContext(script, context);
  return value => {
    context.renderStationTitle(value);
    assert.equal(document.title, heading.textContent);
    return heading.textContent;
  };
}

test('public heading and tab use plain text even for HTML-shaped station titles', async () => {
  const render = await titleRenderer();
  assert.equal(render('  Ptaki nad Wisłą  '), 'Ptaki nad Wisłą');
  const hostile = '<img src=x onerror=alert(1)> & "<script>"';
  assert.equal(render(hostile), hostile);
});

test('old snapshots and malformed titles retain the legacy heading and tab fallback', async () => {
  const render = await titleRenderer();
  for (const value of [undefined, null, 12, {}, '', '   ', 'x'.repeat(121), 'a\nb', 'a\u0000b', 'a\u2028b']) {
    assert.equal(render(value), 'Dźwięki Dolnego Migowa');
  }
  assert.equal(render('ż'.repeat(120)), 'ż'.repeat(120));
});
