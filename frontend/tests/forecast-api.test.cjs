const ts = require('typescript');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../src/lib/forecastApi.ts'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
function client(fetch) {
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', 'fetch', compiled)(
    () => ({ getApiBaseUrl: () => 'http://backend.test' }), mod, mod.exports, fetch,
  );
  return mod.exports;
}
const page = (offset, count, total = 1001, run_id = 'run-1') => ({
  items: Array.from({ length: count }, (_, i) => ({ id: String(offset + i) })),
  total_items: total, run_id,
});
const json = (data, status = 200) => new Response(JSON.stringify(data), { status });
test('loads all pages in order and reports progress with a 30-second default', async () => {
  const offsets = [], progress = [];
  const api = client(async (url) => {
    const params = new URL(url).searchParams;
    assert.equal(params.get('limit'), '500');
    const offset = Number(params.get('offset'));
    if (offset > 0) {
      assert.equal(params.get('source'), 'database');
      assert.equal(params.get('run_id'), 'run-1');
    }
    offsets.push(offset);
    return json(page(offset, Math.min(500, 1001 - offset)));
  });
  assert.equal(api.FORECAST_TIMEOUT_MS, 30000);
  const items = await api.fetchLiveForecast(undefined, undefined, (loaded) => progress.push(loaded));
  assert.equal(items.length, 1001);
  assert.deepEqual(offsets, [0, 500, 1000]);
  assert.deepEqual(progress, [500, 1000, 1001]);
});
test('later-page HTTP failure rejects rather than returning partial data', async () => {
  let calls = 0;
  const api = client(async () => ++calls === 1 ? json(page(0, 500)) : json({ detail: 'Database unavailable' }, 503));
  await assert.rejects(api.fetchLiveForecast(), /HTTP 503: Database unavailable.*\nGET .*offset=500/);
});
test('rejects empty data, invalid metadata, and invalid JSON', async () => {
  for (const [response, pattern] of [
    [json({ items: [], total_items: 0 }), /no forecast items/],
    [json({ items: [{id:'1'}] }), /pagination metadata/],
    [new Response('invalid'), /invalid JSON/],
  ]) await assert.rejects(client(async () => response).fetchLiveForecast(), pattern);
});
test('rejects changed runs and overlapping pages', async () => {
  for (const [second, pattern] of [
    [page(500, 500, 1001, 'run-2'), /changed while loading/],
    [page(0, 500), /overlapping/],
  ]) {
    let calls = 0;
    await assert.rejects(client(async () => json(++calls === 1 ? page(0, 500) : second)).fetchLiveForecast(), pattern);
  }
});
test('timeout also aborts a stalled response body', async () => {
  const api = client(async (_url, {signal}) => ({
    ok: true,
    text: () => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))),
  }));
  await assert.rejects(api.fetchLiveForecast(15), /timed out after 0.015 seconds/);
});
test('cancellation between pages prevents additional requests', async () => {
  const controller = new AbortController();
  let calls = 0;
  const api = client(async () => { calls++; return json(page(0, 500)); });
  await assert.rejects(api.fetchLiveForecast(undefined, controller.signal, () => controller.abort()), { name: 'AbortError' });
  assert.equal(calls, 1);
});

test('cache pages stay on cache when the first page has no run id', async () => {
  let calls = 0;
  const api = client(async (url) => {
    calls++;
    if (calls > 1) assert.equal(new URL(url).searchParams.get('source'), 'cache');
    const payload = page(calls === 1 ? 0 : 500, calls === 1 ? 500 : 1, 501);
    delete payload.run_id;
    return json(payload);
  });
  assert.equal((await api.fetchLiveForecast()).length, 501);
});

test('pins the newly completed run from the first page and rejects a different run', async () => {
  const api = client(async url => {
    const params = new URL(url).searchParams;
    assert.equal(params.get('source'), 'database');
    assert.equal(params.get('run_id'), 'new-run');
    return json(page(0, 1, 1, 'new-run'));
  });
  const items = await api.fetchLiveForecast(undefined, undefined, undefined, 'new-run');
  assert.equal(items[0].run_id, 'new-run');
  await assert.rejects(client(async () => json(page(0, 1, 1, 'old-run')))
    .fetchLiveForecast(undefined, undefined, undefined, 'new-run'), /different forecast run/);
});

test('SHAP cache response is scoped to the selected run/item', async () => {
  const api = client(async (url, options) => {
    assert.equal(options.method, 'POST');
    assert.match(url, /runs\/run-1\/items\/10\/shap$/);
    return json({status:'completed', run_id:'run-1', item_id:'10', item:{id:'10'}});
  });
  const item = await api.loadItemShap('run-1', '10', new AbortController().signal, () => {});
  assert.equal(item.shap_status, 'completed');
  await assert.rejects(client(async () => json({status:'completed',run_id:'old-run',item_id:'10',item:{id:'10'}}))
    .loadItemShap('run-1','10',new AbortController().signal,()=>{}), /different forecast item/);
});

test('SHAP errors are visible and changing selection stops polling', async () => {
  await assert.rejects(client(async () => json({status:'failed',run_id:'r',item_id:'i',error:'Model unavailable'}))
    .loadItemShap('r','i',new AbortController().signal,()=>{}), /Model unavailable/);
  const controller = new AbortController();
  let calls=0;
  const api = client(async () => { calls++; return json({status:'running',run_id:'r',item_id:'i'}); });
  await assert.rejects(api.loadItemShap('r','i',controller.signal,()=>controller.abort()), {name:'AbortError'});
  assert.equal(calls,1);
});
