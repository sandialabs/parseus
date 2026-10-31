'use strict';

// How the page decides the live stream is down and switches to polling.
//
// While the browser is retrying a dropped EventSource itself (readyState
// CONNECTING) it fires an `error` event for every failed attempt, a few seconds
// apart. Counting each of those made a brief server or proxy restart trip the
// fallback after ~9 s. A stream the browser has given up on (CLOSED) is a
// definite failure and still counts immediately.

const test = require('node:test');
const assert = require('node:assert/strict');
const { createPage, makeAlert } = require('./harness');

const CONNECTING = 0;
const CLOSED = 2;
const HEARTBEAT = { interval_seconds: 30 };

async function startedPageWithHealthyStream() {
  const page = await createPage();
  page.start();
  const [source] = page.liveSources();
  source.emit('alert_snapshot', { alerts: { scpi_range: [makeAlert(1)], device: [] }, totals: {} });
  return { page, source };
}

const fallbackQueries = (page) => page.axios.all('alert-query/').length;

test('a short outage (browser retrying every 3 s) does not start fallback polling', async () => {
  const { page, source } = await startedPageWithHealthyStream();

  for (let t = 0; t < 20_000; t += 3_000) {
    source.fail(CONNECTING);
    page.clock.advance(3_000);
  }

  assert.equal(fallbackQueries(page), 0);
  assert.equal(page.get('alertFallbackIntervalId'), null);
});

test('the stream coming back during the grace period cancels the countdown', async () => {
  const { page, source } = await startedPageWithHealthyStream();
  source.fail(CONNECTING);
  page.clock.advance(20_000);

  source.emit('heartbeat', HEARTBEAT); // browser reconnected; server answered
  page.clock.advance(60_000);

  assert.equal(fallbackQueries(page), 0, 'a recovered stream must not fall back later');
});

test('an outage that outlasts the grace period starts fallback polling', async () => {
  const { page, source } = await startedPageWithHealthyStream();

  source.fail(CONNECTING);
  page.clock.advance(29_000);
  assert.equal(fallbackQueries(page), 0, 'not yet');

  page.clock.advance(2_000);

  assert.equal(fallbackQueries(page), 2, 'one query per column once the grace period is over');
  assert.notEqual(page.get('alertFallbackIntervalId'), null);
});

test('repeated errors do not keep pushing the deadline back', async () => {
  const { page, source } = await startedPageWithHealthyStream();

  // Errors every 3 s for the whole outage: if each restarted the countdown it
  // would never fire. It must fire ~30 s after the FIRST error.
  for (let t = 0; t < 33_000; t += 3_000) {
    source.fail(CONNECTING);
    page.clock.advance(3_000);
  }

  assert.equal(fallbackQueries(page), 2);
});

test('polling started by a long outage stops as soon as the stream recovers', async () => {
  const { page, source } = await startedPageWithHealthyStream();
  source.fail(CONNECTING);
  page.clock.advance(31_000);
  assert.notEqual(page.get('alertFallbackIntervalId'), null);

  source.emit('alert_snapshot', { alerts: { scpi_range: [makeAlert(1)], device: [] }, totals: {} });

  assert.equal(page.get('alertFallbackIntervalId'), null);
});

test('a stream the browser gave up on (CLOSED) still counts immediately, not after the grace period', async () => {
  const { page } = await startedPageWithHealthyStream();

  for (let i = 0; i < 3; i += 1) {
    page.liveSources()[0].fail(CLOSED);
    page.clock.advance(31_000); // let each backoff reconnect fire
  }

  assert.equal(fallbackQueries(page) >= 2, true, 'three CLOSED failures trigger the fallback');
});

test('the countdown is tied to one outage: a later, separate blip gets a fresh grace period', async () => {
  const { page, source } = await startedPageWithHealthyStream();

  source.fail(CONNECTING);
  page.clock.advance(10_000);
  source.emit('heartbeat', HEARTBEAT); // outage 1 over
  page.clock.advance(60_000);

  source.fail(CONNECTING); // outage 2 starts at a different time
  page.clock.advance(20_000);

  assert.equal(fallbackQueries(page), 0, 'only 20 s into outage 2, not 80 s since outage 1');
});

test('a stream that never delivers a first frame still falls back (first-snapshot guard)', async () => {
  const page = await createPage();
  page.start();
  assert.equal(page.liveSources().length, 1);

  page.clock.advance(11_000);

  assert.equal(fallbackQueries(page), 2);
  assert.match(page.byId('rangeAlertScreen').textContent, /Unable to load alerts/);
});

test('closing the stream (tab hidden) cancels a pending outage countdown', async () => {
  const { page, source } = await startedPageWithHealthyStream();
  source.fail(CONNECTING);
  page.clock.advance(10_000);

  page.window.closeAlertStream();
  page.clock.advance(60_000);

  assert.equal(fallbackQueries(page), 0, 'a hidden tab must not start polling in the background');
  assert.equal(page.get('alertStreamOutageTimeoutId'), null);
});

test('errors from a replaced connection do not start a countdown', async () => {
  const { page, source } = await startedPageWithHealthyStream();
  source.fail(CLOSED); // browser gave up; page schedules a reconnect and drops this source
  page.clock.advance(31_000); // reconnect opens a fresh source
  const fresh = page.liveSources()[0];
  assert.notEqual(fresh, source);
  fresh.emit('heartbeat', HEARTBEAT);

  source.fail(CONNECTING); // late event from the old, closed connection
  page.clock.advance(60_000);

  assert.equal(page.axios.all('alert-query/').length, 0);
});
