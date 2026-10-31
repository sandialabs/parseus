'use strict';

/*
 * Test harness for the alerts page script (static/js/script.js).
 *
 * Loads the REAL script into a jsdom window containing the page's DOM ids, with:
 *   - a fake axios whose requests stay pending until the test settles them,
 *   - a fake EventSource the test can drive (events, errors, CLOSED),
 *   - a virtual clock replacing the window's timers, so "a day of heartbeats"
 *     or "60 s of a hung request" runs instantly and deterministically.
 *
 * Set ALERTS_SCRIPT_PATH to run the same tests against a different copy of the
 * script (e.g. an older revision, to prove a test fails without its fix).
 */

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM, VirtualConsole } = require('jsdom');

const SCRIPT_PATH = process.env.ALERTS_SCRIPT_PATH
  || path.resolve(__dirname, '..', 'static', 'js', 'script.js');
const SCRIPT_SOURCE = fs.readFileSync(SCRIPT_PATH, 'utf8');

// The ids/classes the script looks up, mirroring templates/alerts/index.html.
const PAGE_HTML = `<!doctype html><html><head><title>Alerts</title></head><body>
<div class="alerts-page-container">
  <div id="alertWatchMode"><div id="alertWatchModeIcon"></div><div id="alertWatchModeLabel"></div>
    <div id="alertModeMessage"></div><span id="totalActiveAlertCount">0</span></div>
  <div id="selectedAlertCount" class="d-none"><span data-selected-alert-count-value>0</span></div>
  <button id="dismissSelectedButton" disabled></button>
  <button id="flagAlertButton" disabled></button>
  <button id="dismissAllButton"></button>
  <div id="scpi_range_alerts">
    <span id="rangeAlertCount">0</span>
    <button data-select-alert-section="scpi_range"><span>Select All</span></button>
    <button data-dismiss-alert-section="scpi_range"></button>
    <p id="rangeAlertScreen"><strong>Loading alerts...</strong></p>
    <div id="rangeResults"></div>
  </div>
  <div id="device-alerts">
    <span id="deviceAlertCount">0</span>
    <button data-select-alert-section="device"><span>Select All</span></button>
    <button data-dismiss-alert-section="device"></button>
    <p id="deviceAlertScreen"><strong>Loading alerts...</strong></p>
    <div id="deviceResults"></div>
  </div>
  <p id="healthLastUpdated"></p>
  ${['logstash', 'gpib', 'disk'].map((service) => `
  <span id="healthStatusLabel-${service}"></span><span id="healthLed-${service}"></span>
  <div id="healthMessage-${service}"></div>`).join('')}
  <div id="diskUsageFill"></div>
</div></body></html>`;

function createClock() {
  let now = 0;
  let nextId = 1;
  const timers = new Map();
  return {
    timers,
    setTimeout(fn, ms = 0) {
      const id = nextId++;
      timers.set(id, { at: now + ms, fn, every: null });
      return id;
    },
    setInterval(fn, ms) {
      const id = nextId++;
      timers.set(id, { at: now + ms, fn, every: ms });
      return id;
    },
    clear(id) {
      timers.delete(id);
    },
    advance(ms) {
      const target = now + ms;
      for (;;) {
        let dueId = null;
        let dueAt = Infinity;
        for (const [id, timer] of timers) {
          if (timer.at < dueAt) {
            dueAt = timer.at;
            dueId = id;
          }
        }
        if (dueId === null || dueAt > target) break;
        const timer = timers.get(dueId);
        now = dueAt;
        if (timer.every) timer.at = now + timer.every;
        else timers.delete(dueId);
        timer.fn();
      }
      now = target;
    },
  };
}

function createAxios() {
  const calls = [];
  const request = (method) => (url, ...rest) => new Promise((resolve, reject) => {
    // get(url, config) vs post(url, data, config)
    const config = method === 'get' ? rest[0] : rest[1];
    // The page lives in jsdom's own JS realm; copy the payload into this one so
    // assertions compare plain data rather than cross-realm objects.
    const data = method === 'get' || rest[0] === undefined ? undefined : JSON.parse(JSON.stringify(rest[0]));
    calls.push({ method, url, data, config, resolve, reject, settled: false });
  });
  return {
    defaults: { headers: { common: {} } },
    get: request('get'),
    post: request('post'),
    calls,
    pending: (url) => calls.filter((call) => !call.settled && (!url || call.url === url)),
    all: (url) => calls.filter((call) => !url || call.url === url),
    respond(call, data = {}) {
      call.settled = true;
      call.resolve({ data });
    },
    fail(call, error) {
      call.settled = true;
      call.reject(error);
    },
  };
}

function createEventSourceClass(instances) {
  return class FakeEventSource {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSED = 2;

    constructor(url) {
      this.url = url;
      this.readyState = FakeEventSource.CONNECTING;
      this.closed = false;
      this.onerror = null;
      this.listeners = {};
      instances.push(this);
    }

    addEventListener(name, fn) {
      (this.listeners[name] ||= []).push(fn);
    }

    close() {
      this.closed = true;
      this.readyState = FakeEventSource.CLOSED;
    }

    emit(name, data) {
      (this.listeners[name] || []).forEach((fn) => fn({ data: JSON.stringify(data) }));
    }

    fail(readyState) {
      this.readyState = readyState;
      if (this.onerror) this.onerror(new Error('stream error'));
    }
  };
}

let alertCounter = 0;
function makeAlert(n, overrides = {}) {
  alertCounter += 1;
  return {
    '@timestamp': `2026-10-28T16:00:${String(n % 60).padStart(2, '0')}.000Z`,
    agent: { type: 'ScpiValueRangesAnalytic' },
    event: { uuid: `u${n}`, original: `alert number ${n} (${alertCounter})` },
    acknowledge: { reason: 'none' },
    ...overrides,
  };
}

/** Build a page with the real script loaded. `start()` fires DOMContentLoaded. */
async function createPage() {
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('error', (...args) => errors.push(args));
  virtualConsole.on('jsdomError', (error) => errors.push([error]));

  const dom = new JSDOM(PAGE_HTML, {
    runScripts: 'outside-only',
    pretendToBeVisual: true,
    url: 'https://localhost/alerts/',
    virtualConsole,
  });
  const { window } = dom;
  const { document } = window;
  if (document.readyState !== 'complete') {
    // jsdom fires its own DOMContentLoaded/load shortly after construction;
    // let that pass first so the script's handler runs exactly once (in start()).
    await new Promise((resolve) => window.addEventListener('load', resolve, { once: true }));
  }

  const clock = createClock();
  const define = (name, value) => Object.defineProperty(window, name, { value, configurable: true, writable: true });
  define('setTimeout', clock.setTimeout);
  define('setInterval', clock.setInterval);
  define('clearTimeout', clock.clear);
  define('clearInterval', clock.clear);

  const axios = createAxios();
  const eventSources = [];
  const toasts = [];
  define('axios', axios);
  define('EventSource', createEventSourceClass(eventSources));
  define('bootstrap', {
    Tooltip: class {
      static getInstance() { return null; }
      dispose() {}
    },
  });
  define('parseusDatetime', { formatTimestamp: (value) => String(value ?? '') });
  define('toastError', (message) => toasts.push({ type: 'error', message }));
  define('toastSuccess', (message) => toasts.push({ type: 'success', message }));
  define('toastWarning', (message) => toasts.push({ type: 'warning', message }));

  // Run as a classic <script> in the window's context (not via window.eval): a
  // script's top-level `let`/`const` then live in the shared global lexical
  // scope, so tests can read state such as `alertActionRequestInFlight`.
  const context = dom.getInternalVMContext();
  new vm.Script(SCRIPT_SOURCE, { filename: SCRIPT_PATH }).runInContext(context);

  const byId = (id) => document.getElementById(id);
  const page = {
    window,
    document,
    clock,
    axios,
    eventSources,
    toasts,
    /** Evaluate an expression in the script's global scope (reads `let` state too). */
    get: (expression) => new vm.Script(expression).runInContext(context),
    liveSources: () => eventSources.filter((source) => !source.closed),
    start() {
      document.dispatchEvent(new window.Event('DOMContentLoaded'));
    },
    /** Push a genuine server snapshot through the same path the SSE handler uses. */
    snapshot(alerts, totals) {
      const fullAlerts = { scpi_range: [], device: [], ...alerts };
      window.renderAlertSnapshot({ alerts: fullAlerts, totals }, { fromServer: true });
    },
    checkbox: (uuid) => document.querySelector(`input.checkbox-alert[data-alert-uuid="${uuid}"]`),
    checkedIds: () => Array.from(document.querySelectorAll('input.checkbox-alert:checked'))
      .map((checkbox) => checkbox.dataset.alertUuid),
    tick(uuid, checked = true) {
      const checkbox = page.checkbox(uuid);
      checkbox.checked = checked;
      checkbox.dispatchEvent(new window.Event('change', { bubbles: true }));
    },
    byId,
    click: (id) => byId(id).click(),
    selectedCountText: () => byId('selectedAlertCount').querySelector('[data-selected-alert-count-value]').textContent,
    /** Let promise continuations (axios .then/.catch/.finally) run. */
    flush: () => new Promise((resolve) => setImmediate(resolve)),
  };
  return page;
}

module.exports = { createPage, makeAlert };
