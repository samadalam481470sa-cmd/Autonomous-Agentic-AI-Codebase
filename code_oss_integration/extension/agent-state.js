'use strict';
// Pure state helpers for the Agent Runs webview. No network, no vscode import.

const MAX_RUNS = 30;
const MAX_DETAIL = 400;

function eventView(event) {
  if (!event || typeof event !== 'object') return {label:'Unknown event', detail:''};
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  const actor = typeof event.actor === 'string' ? event.actor : 'system';
  const cut = value => String(value == null ? '' : value).slice(0, MAX_DETAIL);
  switch (event.type) {
    case 'run.created':
      return {label:'Run created', detail:cut(payload.goal)};
    case 'step.started':
      return {label:'Step started: ' + actor, detail:cut(payload.instruction)};
    case 'step.completed':
      return {label:'Step completed: ' + actor, detail:cut(payload.output)};
    case 'step.failed':
      return {label:'Step failed: ' + actor, detail:cut(payload.error)};
    case 'run.completed':
      return {label:'Run completed', detail:cut(payload.status)};
    case 'run.cancelled':
      return {label:'Run cancelled', detail:cut(payload.reason)};
    case 'executor.started':
      return {label:'Agent started: ' + actor, detail:cut(payload.goal)};
    case 'executor.completed':
      return {label:'Agent finished', detail:cut(payload.final)};
    case 'executor.paused':
      return {label:'Agent paused', detail:cut(payload.final)};
    case 'executor.failed':
      return {label:'Agent failed', detail:cut(payload.error)};
    case 'tool.called':
      return {label:'Tool: ' + cut(payload.tool), detail:cut(payload.target)};
    case 'tool.completed':
      return {label:'Tool result: ' + cut(payload.tool), detail:cut(payload.result)};
    case 'tool.denied':
      return {label:'Tool denied: ' + cut(payload.tool), detail:cut(payload.reason)};
    default:
      return {label:cut(event.type || 'Unknown event'), detail:''};
  }
}

function mergeRuns(runs, incoming) {
  const byId = new Map();
  for (const run of Array.isArray(runs) ? runs : []) {
    if (run && typeof run.id === 'string') byId.set(run.id, run);
  }
  for (const run of Array.isArray(incoming) ? incoming : []) {
    if (run && typeof run.id === 'string') byId.set(run.id, run);
  }
  return [...byId.values()]
    .sort((a, b) => (Number(b.created_at) || 0) - (Number(a.created_at) || 0))
    .slice(0, MAX_RUNS);
}

function progressText(run) {
  if (!run || typeof run !== 'object') return '';
  const progress = run.progress && typeof run.progress === 'object' ? run.progress : {};
  const done = Number(progress.completed) || 0;
  const total = Number(progress.total) || 0;
  return `${run.status || 'unknown'} · ${done}/${total} steps`;
}

module.exports = {eventView, mergeRuns, progressText, MAX_RUNS, MAX_DETAIL};
