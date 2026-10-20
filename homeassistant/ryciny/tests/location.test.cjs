const assert = require('node:assert/strict');
const {test} = require('node:test');
const {parseCoordinates, bind} = require('../app/ryciny/web/location.js');

test('accepts pasted decimal coordinate pairs including negative and boundary values', () => {
  assert.deepEqual(parseCoordinates(' 54.352, 18.646 '), {lat: 54.352, lon: 18.646});
  assert.deepEqual(parseCoordinates('-90; +180'), {lat: -90, lon: 180});
  assert.deepEqual(parseCoordinates('0, 0'), {lat: 0, lon: 0});
});

test('rejects missing, ambiguous, nonfinite, out of range and extra values', () => {
  for (const value of ['', '54', '54,35, 18,64', 'NaN, 2', 'Infinity, 2', '91, 0', '0,-181', '1,2,3', '1e2,2', '<b>1,2</b>']) {
    assert.throws(() => parseCoordinates(value), Error, value);
  }
});

function fixture(save, geolocation) {
  const callbacks = {};
  const input = {value: '', defaultValue: '', setCustomValidity(value) { this.error = value; }, reportValidity() {},
    addEventListener(event, handler) { callbacks['input:' + event] = handler; }};
  const status = {textContent: '', classList: {toggle() {}}};
  const fields = {disabled: false};
  const device = {addEventListener(event, handler) { callbacks['device:' + event] = handler; }};
  const form = {querySelector(selector) { return {input, fieldset: fields, '[role=status]': status, '[data-location-device]': device}[selector]; },
    addEventListener(event, handler) { callbacks[event] = handler; }};
  bind(form, {lat: 54.352, lon: 18.646}, save, geolocation);
  return {callbacks, input, status, fields, device, submit: () => callbacks.submit({preventDefault() {}})};
}

test('explicit save submits the complete pair and reset restores the persisted pair', async () => {
  const requests = [];
  const f = fixture(async pair => { requests.push(pair); return pair; });
  f.input.value = '52.1, 21.2';
  await f.submit();
  assert.deepEqual(requests, [{lat: 52.1, lon: 21.2}]);
  f.input.value = '0,0';
  f.callbacks.reset();
  assert.equal(f.input.value, '52.1, 21.2');
  assert.equal(f.fields.disabled, false);
});

test('failed save retains the draft, invalid input makes no request', async () => {
  let requests = 0;
  const f = fixture(async () => { requests++; return null; });
  f.input.value = '1,2';
  await f.submit();
  assert.equal(f.input.value, '1,2');
  assert.match(f.status.textContent, /Nie udało/);
  f.input.value = '91,2';
  await f.submit();
  assert.equal(requests, 1);
  assert.equal(f.fields.disabled, false);
});

test('device GPS fills a draft without saving; denial preserves manual editing', () => {
  let requests = 0, success, failure;
  const f = fixture(() => { requests++; }, {getCurrentPosition(ok, fail) { success = ok; failure = fail; }});
  f.callbacks['device:click']();
  success({coords: {latitude: 52.1, longitude: 21.2}});
  assert.equal(f.input.value, '52.100000, 21.200000');
  assert.equal(requests, 0);
  f.callbacks['device:click']();
  failure();
  assert.equal(f.fields.disabled, false);
  assert.equal(f.input.value, '52.100000, 21.200000');
  assert.match(f.status.textContent, /ręcznie/);
  assert.equal(fixture(() => {}).device.disabled, true);
});
