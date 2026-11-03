'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {eventView, mergeRuns, progressText, MAX_DETAIL} = require('./agent-state.js');

test('run and step events become bounded evidence rows', () => {
  assert.deepEqual(eventView({type:'run.created', payload:{goal:'Ship it'}}),
    {label:'Run created', detail:'Ship it'});
  const long = eventView({type:'step.completed', actor:'coder', payload:{output:'x'.repeat(2000)}});
  assert.equal(long.label, 'Step completed: coder');
  assert.equal(long.detail.length, MAX_DETAIL);
});

test('tool denials expose the policy reason, not a credential', () => {
  const view = eventView({type:'tool.denied', payload:{tool:'write_file', reason:'ask_mode_cannot_change_state'}});
  assert.equal(view.label, 'Tool denied: write_file');
  assert.equal(view.detail, 'ask_mode_cannot_change_state');
});

test('mergeRuns deduplicates by id and keeps the newest first', () => {
  const merged = mergeRuns(
    [{id:'a', created_at:1}, {id:'b', created_at:2}],
    [{id:'a', created_at:3, status:'completed'}]
  );
  assert.deepEqual(merged.map(run => run.id), ['a', 'b']);
  assert.equal(merged[0].status, 'completed');
});

test('progress text is defensive about missing fields', () => {
  assert.equal(progressText({status:'queued', progress:{completed:1, total:5}}), 'queued · 1/5 steps');
  assert.equal(progressText(null), '');
});
