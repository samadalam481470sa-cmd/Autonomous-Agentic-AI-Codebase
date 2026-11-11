'use strict';
// Cursor-style inline completions for the Code-OSS overlay.
// Sends only the cursor window to the loopback backend; the admin token stays
// in SecretStorage and is never exposed to the webview.
const vscode = require('vscode');
const {localEndpoint, validProject} = require('./sse.js');

const SECRET = 'agenticLocal.adminToken';
const MAX_PREFIX = 6000;
const MAX_SUFFIX = 2000;
const TIMEOUT_MS = 9000;

function settings() {
  return vscode.workspace.getConfiguration('agenticLocal');
}

function allowedDocument(document) {
  return ['file', 'untitled', 'vscode-remote'].includes(document.uri.scheme);
}

async function requestCompletion(context, document, position, cancelToken) {
  const config = settings();
  if (config.get('completions', true) !== true) return null;
  if (!allowedDocument(document)) return null;
  let endpoint;
  try {
    endpoint = localEndpoint(config.get('endpoint', 'http://127.0.0.1:8000'));
  } catch (_) {
    return null;
  }
  const project = config.get('project', 'demo');
  if (!validProject(project)) return null;
  const token = await context.secrets.get(SECRET);
  if (!token) return null;

  const text = document.getText();
  const offset = document.offsetAt(position);
  const prefix = text.slice(Math.max(0, offset - MAX_PREFIX), offset);
  if (prefix.trim().length < 8) return null;
  const suffix = text.slice(offset, offset + MAX_SUFFIX);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  const cancel = cancelToken.onCancellationRequested(() => controller.abort());
  try {
    const response = await fetch(endpoint + '/api/ai/complete', {
      method: 'POST',
      signal: controller.signal,
      redirect: 'error',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token,
      },
      body: JSON.stringify({
        project,
        path: document.uri.path || document.fileName,
        prefix,
        suffix,
        max_tokens: 128,
      }),
    });
    if (!response.ok) return null;
    const data = await response.json();
    if (!data || typeof data.completion !== 'string' || !data.completion) return null;
    if (cancelToken.isCancellationRequested) return null;
    return data.completion;
  } catch (_) {
    return null;
  } finally {
    clearTimeout(timer);
    cancel.dispose();
  }
}

function registerCompletions(context) {
  const provider = {
    async provideInlineCompletionItems(document, position, _context, token) {
      const completion = await requestCompletion(context, document, position, token);
      if (!completion) return {items: []};
      return {
        items: [new vscode.InlineCompletionItem(
          completion, new vscode.Range(position, position)
        )],
      };
    },
  };
  return vscode.languages.registerInlineCompletionItemProvider({pattern: '**'}, provider);
}

module.exports = {registerCompletions, requestCompletion};
