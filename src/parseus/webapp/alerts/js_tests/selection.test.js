'use strict';

// The operator's checkbox selection must survive the list being rebuilt.
// Alerts arrive continuously, and every changed snapshot rebuilds the rows; a
// selection that vanished on each rebuild made multi-selecting impractical.

const test = require('node:test');
const assert = require('node:assert/strict');
const { createPage, makeAlert } = require('./harness');

test('ticked alerts stay ticked when a changed snapshot rebuilds the list', async () => {
  const page = await createPage();
  page.snapshot({ scpi_range: [makeAlert(1), makeAlert(2), makeAlert(3)] });
  page.tick('u2');
  const rowBefore = page.checkbox('u2');

  // A new detection arrives at the top: the list changes, so it is rebuilt.
  page.snapshot({ scpi_range: [makeAlert(0), makeAlert(1), makeAlert(2), makeAlert(3)] });

  assert.notEqual(page.checkbox('u2'), rowBefore, 'precondition: the row really was rebuilt');
  assert.deepEqual(page.checkedIds(), ['u2']);
  assert.equal(page.selectedCountText(), '1');
  assert.equal(page.byId('flagAlertButton').disabled, false, 'selection actions stay usable');
  assert.equal(page.byId('dismissSelectedButton').disabled, false);
});

test('a selection is kept across many consecutive rebuilds', async () => {
  const page = await createPage();
  const alerts = [makeAlert(1), makeAlert(2)];
  page.snapshot({ scpi_range: alerts });
  page.tick('u1');

  for (let n = 10; n < 60; n += 1) {
    alerts.unshift(makeAlert(n));
    page.snapshot({ scpi_range: [...alerts] });
  }

  assert.deepEqual(page.checkedIds(), ['u1']);
});

test('an alert that disappears is dropped from the selection, not resurrected', async () => {
  const page = await createPage();
  page.snapshot({ scpi_range: [makeAlert(1), makeAlert(2), makeAlert(3)] });
  page.tick('u1');
  page.tick('u3');

  page.snapshot({ scpi_range: [makeAlert(2), makeAlert(3)] }); // u1 was handled elsewhere

  assert.deepEqual(page.checkedIds(), ['u3']);
  assert.equal(page.selectedCountText(), '1');

  page.snapshot({ scpi_range: [makeAlert(1), makeAlert(2), makeAlert(3)] }); // u1 is back
  assert.deepEqual(page.checkedIds(), ['u3'], 'a stale selection must not re-apply to a returning alert');
});

test('selection is dropped to zero and the actions disable when every selected alert disappears', async () => {
  const page = await createPage();
  page.start();
  page.snapshot({ scpi_range: [makeAlert(1), makeAlert(2)] });
  page.tick('u1');
  assert.equal(page.byId('flagAlertButton').disabled, false);

  page.snapshot({ scpi_range: [makeAlert(2)] });

  assert.deepEqual(page.checkedIds(), []);
  assert.equal(page.byId('flagAlertButton').disabled, true);
  assert.equal(page.byId('selectedAlertCount').classList.contains('d-none'), true);
});

test('keyboard focus on a checkbox survives the rebuild', async () => {
  const page = await createPage();
  page.snapshot({ scpi_range: [makeAlert(1), makeAlert(2)] });
  page.checkbox('u2').focus();
  assert.equal(page.document.activeElement.dataset.alertUuid, 'u2');

  page.snapshot({ scpi_range: [makeAlert(0), makeAlert(1), makeAlert(2)] });

  assert.equal(page.document.activeElement.dataset.alertUuid, 'u2');
  assert.equal(page.document.activeElement, page.checkbox('u2'), 'focus is on the NEW row');
});

test('an unchanged snapshot does not rebuild the rows at all', async () => {
  const page = await createPage();
  const alerts = [makeAlert(1), makeAlert(2)];
  page.snapshot({ scpi_range: alerts });
  const rowBefore = page.checkbox('u1');

  page.snapshot({ scpi_range: alerts });

  assert.equal(page.checkbox('u1'), rowBefore);
});

test('a change in one column leaves the other column\'s selection alone', async () => {
  const page = await createPage();
  page.snapshot({ scpi_range: [makeAlert(1)], device: [makeAlert(5)] });
  page.tick('u1');
  page.tick('u5');

  page.snapshot({ scpi_range: [makeAlert(1)], device: [makeAlert(6), makeAlert(5)] });

  assert.deepEqual(page.checkedIds().sort(), ['u1', 'u5']);
});

test('Flag Selected consumes the selection, and a failed request gives it back', async () => {
  const page = await createPage();
  page.start();
  page.snapshot({ scpi_range: [makeAlert(1), makeAlert(2), makeAlert(3)] });
  page.tick('u1');
  page.tick('u3');

  page.click('flagAlertButton');
  assert.deepEqual(page.checkedIds(), [], 'the flagged alerts stay on screen but are no longer selected');

  const [call] = page.axios.pending('handle-alerts/');
  assert.deepEqual(call.data, { handle_type: 'flagged', uuids: ['u1', 'u3'] });
  page.axios.fail(call, { response: { data: { error: 'boom' } } });
  await page.flush();

  assert.deepEqual(page.checkedIds().sort(), ['u1', 'u3'], 'the operator can retry without re-selecting');
  assert.equal(page.byId('flagAlertButton').disabled, false);
});

test('Flag Selected leaves nothing selected after the request succeeds', async () => {
  const page = await createPage();
  page.start();
  page.snapshot({ scpi_range: [makeAlert(1), makeAlert(2)] });
  page.tick('u1');

  page.click('flagAlertButton');
  page.axios.respond(page.axios.pending('handle-alerts/')[0], { message: '1 alert flagged' });
  await page.flush();

  assert.deepEqual(page.checkedIds(), []);
  assert.equal(page.byId('flagAlertButton').disabled, true, 'nothing selected, so nothing to act on');
});

test('Dismiss Selected removes the alerts and leaves no stale selection', async () => {
  const page = await createPage();
  page.start();
  page.snapshot({ scpi_range: [makeAlert(1), makeAlert(2), makeAlert(3)] });
  page.tick('u1');
  page.tick('u2');

  page.click('dismissSelectedButton');
  page.axios.respond(page.axios.pending('handle-alerts/')[0], { message: '2 alerts dismissed' });
  await page.flush();

  assert.equal(page.checkbox('u1'), null);
  assert.equal(page.checkbox('u2'), null);
  assert.ok(page.checkbox('u3'));
  assert.deepEqual(page.checkedIds(), []);
});
