'use strict';

// Every request must be bounded, and the timer-driven ones must not pile up.
//
// axios has no timeout by default. A request whose connection stalls never
// settles, so its .finally never runs: a hung dismiss/flag POST left the action
// buttons disabled until the operator reloaded the page, and the 30s/60s timers
// kept stacking new requests behind a hung one.

const test = require('node:test');
const assert = require('node:assert/strict');
const { createPage, makeAlert } = require('./harness');

const timeoutError = () => Object.assign(new Error('timeout of 15000ms exceeded'), { code: 'ECONNABORTED' });

test('axios is given a default timeout', async () => {
  const page = await createPage();
  const timeout = page.get('axios.defaults.timeout');
  assert.ok(Number.isFinite(timeout) && timeout > 0 && timeout <= 30000, `default timeout was ${timeout}`);
});

test('dismiss/flag POSTs carry an explicit, longer timeout below nginx\'s 90 s', async () => {
  const page = await createPage();
  page.start();
  page.snapshot({ scpi_range: [makeAlert(1)] });
  page.tick('u1');

  page.click('flagAlertButton');
  page.click('dismissAllButton');

  const handle = page.axios.pending('handle-alerts/')[0];
  assert.ok(handle.config.timeout > page.get('axios.defaults.timeout'), 'actions may take longer than reads');
  assert.ok(handle.config.timeout < 90000, 'must fire before nginx answers with its own 504');
});

test('a timed-out dismiss re-enables the buttons and says why', async () => {
  const page = await createPage();
  page.start();
  page.snapshot({ scpi_range: [makeAlert(1), makeAlert(2)] });

  page.click('dismissAllButton');
  assert.equal(page.byId('dismissAllButton').disabled, true, 'disabled while the request is in flight');

  page.axios.fail(page.axios.pending('clear-all/')[0], timeoutError());
  await page.flush();

  assert.equal(page.byId('dismissAllButton').disabled, false, 'operator can try again');
  assert.ok(page.toasts.some((t) => /did not respond in time/i.test(t.message)), JSON.stringify(page.toasts));
  assert.ok(page.checkbox('u1'), 'the optimistic removal was rolled back');
});

test('a timed-out flag re-enables the actions', async () => {
  const page = await createPage();
  page.start();
  page.snapshot({ scpi_range: [makeAlert(1)] });
  page.tick('u1');

  page.click('flagAlertButton');
  page.axios.fail(page.axios.pending('handle-alerts/')[0], timeoutError());
  await page.flush();

  assert.equal(page.get('alertActionRequestInFlight'), false);
  assert.equal(page.byId('dismissAllButton').disabled, false);
  assert.deepEqual(page.checkedIds(), ['u1']);
});

test('a hung health request does not stack another every 60 s', async () => {
  const page = await createPage();
  page.start(); // fires the first refresh at startup
  assert.equal(page.axios.all('monitor-health/').length, 1);

  page.clock.advance(60_000 * 5); // five intervals, the first request never settles

  assert.equal(page.axios.all('monitor-health/').length, 1, 'no overlapping health requests');
});

test('health refresh resumes after the hung request fails', async () => {
  const page = await createPage();
  page.start();
  page.axios.fail(page.axios.pending('monitor-health/')[0], timeoutError());
  await page.flush();

  page.clock.advance(60_000);

  assert.equal(page.axios.pending('monitor-health/').length, 1, 'next interval issues a fresh request');
});

test('health refresh resumes after a successful response too', async () => {
  const page = await createPage();
  page.start();
  page.axios.respond(page.axios.pending('monitor-health/')[0], { services: {}, checked_at: '2026-10-28T00:00:00Z' });
  await page.flush();

  page.clock.advance(60_000);

  assert.equal(page.axios.pending('monitor-health/').length, 1);
});

test('fallback polling does not stack queries behind a hung one, per column', async () => {
  const page = await createPage();
  // No EventSource: the page falls back to polling straight away.
  page.window.EventSource = undefined;
  page.start();
  assert.equal(page.axios.all('alert-query/').length, 2, 'one query per column at startup');

  page.clock.advance(30_000 * 4); // four fallback ticks, nothing ever settles

  assert.equal(page.axios.all('alert-query/').length, 2, 'still only the two original queries');
});

test('one hung column does not block the other column\'s polling', async () => {
  const page = await createPage();
  page.window.EventSource = undefined;
  page.start();
  const [scpi, device] = page.axios.pending('alert-query/');
  assert.equal(scpi.data.alert_type, 'scpi_range');
  assert.equal(device.data.alert_type, 'device');

  page.axios.respond(device, { alerts: [], total: 0 }); // device answers, scpi hangs
  await page.flush();
  page.clock.advance(30_000);

  const all = page.axios.all('alert-query/');
  assert.equal(all.length, 3, 'device was polled again; scpi was skipped because its query is still outstanding');
  assert.equal(all[2].data.alert_type, 'device');
});

test('fallback polling resumes after a failed query', async () => {
  const page = await createPage();
  page.window.EventSource = undefined;
  page.start();
  for (const call of page.axios.pending('alert-query/')) page.axios.fail(call, timeoutError());
  await page.flush();

  page.clock.advance(30_000);

  assert.equal(page.axios.pending('alert-query/').length, 2);
});
