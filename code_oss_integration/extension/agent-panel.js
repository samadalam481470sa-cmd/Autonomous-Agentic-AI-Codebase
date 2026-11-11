'use strict';
// Agent Runs webview: authenticated orchestration only, never a model key.
const vscode = require('vscode');
const crypto = require('node:crypto');
const {localEndpoint, validProject} = require('./sse.js');
const {eventView, mergeRuns, progressText} = require('./agent-state.js');

const SECRET = 'agenticLocal.adminToken';

class AgentPanel {
  constructor(context) {
    this.context = context;
    this.view = null;
    this.runs = [];
    this.selected = null;
    this.events = [];
    this.busy = false;
    this.timer = null;
  }

  resolveWebviewView(view) {
    this.view = view;
    const nonce = crypto.randomBytes(16).toString('hex');
    view.webview.options = {enableScripts: true, localResourceRoots: []};
    view.webview.html = this.html(nonce);
    view.webview.onDidReceiveMessage(message => this.onMessage(message));
    this.timer = setInterval(() => {
      if (this.view && this.view.visible && !this.busy) this.refresh();
    }, 2500);
    this.refresh();
  }

  async onMessage(message) {
    if (!message || typeof message !== 'object') return;
    try {
      if (message.type === 'refresh') await this.refresh();
      if (message.type === 'select' && typeof message.id === 'string') {
        this.selected = this.runs.find(run => run.id === message.id) || null;
        await this.loadEvents();
        this.postState();
      }
      if (message.type === 'create') await this.create(message.goal);
      if (message.type === 'advance') await this.act('advance');
      if (message.type === 'cancel') await this.act('cancel');
    } catch (error) {
      this.post({type: 'error', text: String(error && error.message || error).slice(0, 300)});
    }
  }

  async connection() {
    const token = await this.context.secrets.get(SECRET);
    if (!token) throw new Error('Connect to the local backend first');
    const config = vscode.workspace.getConfiguration('agenticLocal');
    const endpoint = localEndpoint(config.get('endpoint', 'http://127.0.0.1:8000'));
    const project = config.get('project', 'demo');
    if (!validProject(project)) throw new Error('Invalid local project name');
    return {token, endpoint, project};
  }

  async api(path, options = {}) {
    const {token, endpoint} = await this.connection();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(endpoint + path, {
        ...options,
        signal: controller.signal,
        redirect: 'error',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + token,
          ...(options.headers || {}),
        },
      });
      if (!response.ok) throw new Error('Local API HTTP ' + response.status);
      return await response.json();
    } finally {
      clearTimeout(timer);
    }
  }

  async refresh() {
    if (this.busy) return;
    this.busy = true;
    try {
      const {project} = await this.connection();
      const data = await this.api('/api/agents/runs?project=' + encodeURIComponent(project) + '&limit=30');
      this.runs = mergeRuns(this.runs, data.runs);
      if (this.selected) {
        this.selected = this.runs.find(run => run.id === this.selected.id) || null;
        if (this.selected) await this.loadEvents();
      }
      this.postState();
    } finally {
      this.busy = false;
    }
  }

  async loadEvents() {
    if (!this.selected) {this.events = [];return;}
    const data = await this.api(
      `/api/agents/runs/${encodeURIComponent(this.selected.id)}/events?after=0&limit=500`
    );
    this.events = Array.isArray(data.events) ? data.events.slice(-500) : [];
  }

  async create(goal) {
    if (typeof goal !== 'string' || goal.trim().length < 8 || goal.length > 4000) {
      throw new Error('Goal must be between 8 and 4000 characters');
    }
    const {project} = await this.connection();
    const run = await this.api('/api/agents/runs', {
      method: 'POST',
      body: JSON.stringify({project, goal: goal.trim(), mode: 'build'}),
    });
    this.runs = mergeRuns(this.runs, [run]);
    this.selected = run;
    this.events = [];
    this.postState();
  }

  async act(action) {
    if (!this.selected) throw new Error('Select a run first');
    const run = await this.api(
      `/api/agents/runs/${encodeURIComponent(this.selected.id)}/${action}`,
      {method: 'POST'}
    );
    this.runs = mergeRuns(this.runs, [run]);
    this.selected = run;
    await this.loadEvents();
    this.postState();
  }

  postState() {
    this.post({
      type: 'state',
      runs: this.runs.map(run => ({
        id: run.id, goal: run.goal, status: run.status, mode: run.mode,
        progress: progressText(run),
      })),
      selected: this.selected ? {
        id: this.selected.id, goal: this.selected.goal, status: this.selected.status,
        steps: Array.isArray(this.selected.steps) ? this.selected.steps.map(step => ({
          role: step.role, status: step.status,
        })) : [],
      } : null,
      events: this.events.map(eventView),
    });
  }

  post(message) {this.view && this.view.webview.postMessage(message);}

  html(nonce) {
    return `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}'">
<meta name="viewport" content="width=device-width,initial-scale=1"><style nonce="${nonce}">
:root{font:13px system-ui;color:var(--vscode-foreground);background:var(--vscode-sideBar-background)}
body{margin:0;padding:10px;display:flex;flex-direction:column;gap:9px;height:100vh;box-sizing:border-box}
h2{font-size:13px;margin:0;text-transform:uppercase;letter-spacing:.04em;opacity:.8}
#runs{max-height:130px;overflow:auto;display:flex;flex-direction:column;gap:4px}
.run{text-align:left;background:var(--vscode-editor-background);color:var(--vscode-foreground);border:1px solid var(--vscode-panel-border);padding:6px;border-radius:4px;cursor:pointer;overflow:hidden}
.run.active{border-color:var(--vscode-focusBorder)}
.run small{opacity:.75;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
textarea{width:100%;box-sizing:border-box;min-height:60px;resize:vertical;background:var(--vscode-input-background);color:var(--vscode-input-foreground);border:1px solid var(--vscode-input-border);padding:7px}
#actions{display:flex;flex-wrap:wrap;gap:6px}button{background:var(--vscode-button-background);color:var(--vscode-button-foreground);border:0;padding:6px 8px;border-radius:4px;cursor:pointer}button.secondary{background:var(--vscode-button-secondaryBackground);color:var(--vscode-button-secondaryForeground)}
#status{font-size:12px;opacity:.8;min-height:16px}
#evidence{flex:1;overflow:auto;border-top:1px solid var(--vscode-panel-border);padding-top:6px}
.event{padding:4px 0;border-bottom:1px solid var(--vscode-panel-border)}
.event b{display:block}.event span{opacity:.8;white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}
</style></head><body>
<h2>Agent Runs</h2><div id="runs"><small>Connect and refresh.</small></div>
<label for="goal">New goal</label><textarea id="goal" maxlength="4000" aria-label="New agent goal"></textarea>
<div id="actions"><button id="create">New run</button><button id="advance" class="secondary">Advance one step</button><button id="cancel" class="secondary">Cancel</button><button id="refresh" class="secondary">Refresh</button></div>
<div id="status">Disconnected</div><div id="evidence"></div>
<script nonce="${nonce}">
const vscode=acquireVsCodeApi(),get=id=>document.getElementById(id),runsEl=get('runs'),evidence=get('evidence'),status=get('status');
let selected=null;
get('create').onclick=()=>vscode.postMessage({type:'create',goal:get('goal').value});
get('advance').onclick=()=>vscode.postMessage({type:'advance'});
get('cancel').onclick=()=>vscode.postMessage({type:'cancel'});
get('refresh').onclick=()=>vscode.postMessage({type:'refresh'});
function renderRuns(items){runsEl.textContent='';if(!items.length){const s=document.createElement('small');s.textContent='No runs yet.';runsEl.append(s);return;}
for(const run of items){const b=document.createElement('button');b.className='run'+(selected&&selected.id===run.id?' active':'');b.dataset.id=run.id;const t=document.createElement('span');t.textContent=run.goal.slice(0,90);const s=document.createElement('small');s.textContent=run.progress;b.append(t,s);b.onclick=()=>vscode.postMessage({type:'select',id:run.id});runsEl.append(b);}}
function renderEvents(items){evidence.textContent='';for(const item of items){const row=document.createElement('div');row.className='event';const b=document.createElement('b');b.textContent=item.label;row.append(b);if(item.detail){const s=document.createElement('span');s.textContent=item.detail;row.append(s);}evidence.append(row);}}
window.addEventListener('message',event=>{const m=event.data;if(!m||typeof m!=='object')return;
if(m.type==='error'){status.textContent=m.text;return;}
if(m.type!=='state')return;selected=m.selected;renderRuns(Array.isArray(m.runs)?m.runs:[]);renderEvents(Array.isArray(m.events)?m.events:[]);status.textContent=selected?(selected.status+' · '+selected.steps.map(x=>x.role+':'+x.status).join(' · ')):'Connected';});
</script></body></html>`;
  }

  dispose() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.view = null;
  }
}

module.exports = {AgentPanel};
