'use strict';
// First-party Code-OSS extension overlay. Never send credentials to webview JS.
const vscode = require('vscode');
const crypto = require('node:crypto');
const {parseAvailable, localEndpoint, validProject} = require('./sse.js');
const {rewriteSelection}=require('./rewrite-selection.js');
const {AgentPanel}=require('./agent-panel.js');
const {registerCompletions}=require('./completions.js');

const SECRET = 'agenticLocal.adminToken';
function escapeHtml(value) {return String(value).replace(/[&<>"']/g, c => ({
  '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
}[c]));}

class ChatView {
  constructor(context) {this.context=context;this.view=null;this.controller=null;this.busy=false;}
  resolveWebviewView(view) {
    this.view = view;
    const nonce = crypto.randomBytes(16).toString('hex');
    view.webview.options = {enableScripts:true, localResourceRoots:[]};
    view.webview.html = this.html(nonce);
    view.webview.onDidReceiveMessage(async message => {
      if (message && message.type === 'models') {this.models();return;}
      if (!message || typeof message !== 'object') return;
      if (message.type === 'stop') {this.controller?.abort();return;}
      if (message.type === 'connect') {await vscode.commands.executeCommand('agenticLocal.connect');return;}
      if (message.type === 'send') {
        if (typeof message.text !== 'string' || !message.text.trim() || message.text.length > 12000) return;
        await this.ask(message.text.trim(), message.model);
      }
    });
  }
  html(nonce) {
    return `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}'">
<meta name="viewport" content="width=device-width,initial-scale=1"><style nonce="${nonce}">
:root{font:13px system-ui;color:var(--vscode-foreground);background:var(--vscode-sideBar-background)}
body{margin:0;display:flex;flex-direction:column;height:100vh;padding:12px;gap:10px;box-sizing:border-box}
#thread{flex:1;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}
.message{background:var(--vscode-editor-background);border:1px solid var(--vscode-panel-border);padding:10px;border-radius:7px;margin-bottom:9px}
.message.user{border-left:3px solid var(--vscode-focusBorder)}
textarea{width:100%;box-sizing:border-box;min-height:76px;resize:vertical;background:var(--vscode-input-background);color:var(--vscode-input-foreground);border:1px solid var(--vscode-input-border);padding:8px}
button{background:var(--vscode-button-background);color:var(--vscode-button-foreground);border:0;padding:8px 9px;cursor:pointer;border-radius:5px}
button:disabled{opacity:.45}#actions{display:flex;gap:8px}#status{opacity:.85;font-size:12px}
</style></head><body>
<div id="thread"><div class="message">Runs on your computer. Configure LOCAL_MODEL_ONLY=1 and start the Python/Rust services, then connect using your local admin token. This chat never executes tools.</div></div>
<label for="model">Model</label><select id="model" aria-label="Model"><option value="">Default</option></select>
<label for="prompt">Ask your local model</label><textarea id="prompt" maxlength="12000" aria-label="Local AI prompt"></textarea>
<div id="actions"><button id="send">Send</button><button id="stop" disabled>Stop</button><button id="connect">Connect</button></div><div id="status">Disconnected</div>
<script nonce="${nonce}">
const vscode=acquireVsCodeApi(),get=id=>document.getElementById(id),thread=get('thread');
let current=null;
function add(cls,text){const node=document.createElement('div');node.className='message '+cls;node.textContent=text;thread.append(node);thread.scrollTop=thread.scrollHeight;return node}
get('send').onclick=()=>{const text=get('prompt').value.trim();if(!text)return;add('user',text);get('prompt').value='';current=add('assistant','');get('send').disabled=true;get('stop').disabled=false;vscode.postMessage({type:'send',text,model:get('model').value||null})};
get('stop').onclick=()=>vscode.postMessage({type:'stop'});
get('connect').onclick=()=>vscode.postMessage({type:'connect'});
window.addEventListener('message',event=>{
const m=event.data;if(!m||typeof m!=='object')return;
if(m.type==='delta'){if(current)current.textContent+=m.text;thread.scrollTop=thread.scrollHeight;}
if(m.type==='status')get('status').textContent=m.text;
if(m.type==='models'){const box=get('model');const keep=box.value;box.textContent='';box.append(new Option('Default',''));for(const item of (m.models||[]))box.append(new Option(item.label,item.id));box.value=keep;}
if(m.type==='error'){if(current)current.textContent+='\\n[Error: '+m.text+']';get('status').textContent='Local model unavailable';}
if(m.type==='done'){get('send').disabled=false;get('stop').disabled=true;current=null}
if(m.type==='prefill')get('prompt').value=m.text;
});
</script></body></html>`;
  }
  post(type, content) {this.view?.webview.postMessage({type, ...content});}
  async models() {
    const token = await this.context.secrets.get(SECRET);
    if (!token) return;
    let endpoint;
    try {endpoint=localEndpoint(vscode.workspace.getConfiguration('agenticLocal').get('endpoint','http://127.0.0.1:8000'));}
    catch (_) {return;}
    try {
      const response=await fetch(endpoint+'/api/models',{
        redirect:'error',headers:{'Authorization':'Bearer '+token}
      });
      if(!response.ok)return;
      const data=await response.json();
      const models=Array.isArray(data.models)?data.models.map(m=>({id:m.id,label:m.label})):[];
      this.post('models',{models,default:data.default});
    } catch (_) {return;}
  }
  async ask(text, model) {
    if (this.busy) return;
    const token = await this.context.secrets.get(SECRET);
    if (!token) {this.post('error',{text:'Connect to the local backend first'});this.post('done',{});return;}
    const config = vscode.workspace.getConfiguration('agenticLocal');
    let endpoint;
    try {endpoint=localEndpoint(config.get('endpoint','http://127.0.0.1:8000'));}
    catch (e) {this.post('error',{text:e.message});this.post('done',{});return;}
    const project=config.get('project','demo');
    if (!validProject(project)) {this.post('error',{text:'Invalid local project name'});this.post('done',{});return;}
    this.busy = true;
    const controller = new AbortController();this.controller=controller;
    const timer=setTimeout(()=>controller.abort(),180000);
    let buffer='', completed=false;
    this.post('status',{text:'Streaming from '+endpoint});
    try {
      const response=await fetch(endpoint+'/api/chat/stream',{
        method:'POST',signal:controller.signal,redirect:'error',
        headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},
        body:JSON.stringify({project,message:text,model:model||null})
      });
      if (!response.ok || !response.body) throw new Error('Local chat HTTP '+response.status);
      const reader=response.body.getReader();
      const decoder=new TextDecoder();
      try {
        while(true) {
          const {value,done}=await reader.read();
          if(done)break;
          buffer+=decoder.decode(value,{stream:true});
          const parsed=parseAvailable(buffer);buffer=parsed.rest;
          for(const item of parsed.events) {
            if(item.kind==='delta') {
              if(typeof item.payload.text!=='string') throw new Error('Invalid text delta');
              this.post('delta',{text:item.payload.text});
            } else if(item.kind==='error') {
              throw new Error('Local model streaming returned an error');
            } else if(item.kind==='done') {
              completed=true;
            }
          }
        }
      } finally {reader.releaseLock();}
      if(!completed)throw new Error('Stream ended without completion');
      this.post('status',{text:'Local response completed'});
    } catch (err) {
      this.post('error',{text:controller.signal.aborted?'Stream stopped':String(err.message||err)});
    } finally {
      clearTimeout(timer);this.controller=null;this.busy=false;this.post('done',{});
    }
  }
  prefill(text) {this.view?.show?.(true);this.post('prefill',{text});}
  dispose() {this.controller?.abort();}
}

async function activate(context) {
  const view=new ChatView(context);
  const agent=new AgentPanel(context);
  context.subscriptions.push(vscode.window.registerWebviewViewProvider('agenticLocal.chat',view));
  context.subscriptions.push(vscode.window.registerWebviewViewProvider('agenticLocal.agent',agent));
  context.subscriptions.push({dispose:()=>{view.dispose();agent.dispose();}});
  context.subscriptions.push(vscode.commands.registerCommand('agenticLocal.openAgent',()=>
    vscode.commands.executeCommand('workbench.view.extension.agenticLocal')));
  context.subscriptions.push(vscode.commands.registerCommand('agenticLocal.connect',async()=>{
    const secret=await vscode.window.showInputBox({
      title:'Connect Local AI',prompt:'Enter AGENT_ADMIN_TOKEN from your local backend',
      password:true,ignoreFocusOut:true,validateInput:value=>value.trim().length<12?'Use a nontrivial local admin token':null
    });
    if(!secret)return;
    await context.secrets.store(SECRET,secret);
    vscode.window.showInformationMessage('Local AI token saved in VS Code SecretStorage (not the workspace).');
  }));
  context.subscriptions.push(registerCompletions(context));
  context.subscriptions.push(vscode.commands.registerCommand('agenticLocal.rewriteSelection',()=>rewriteSelection(vscode,context,SECRET)));
  context.subscriptions.push(vscode.commands.registerCommand('agenticLocal.askSelection',async()=>{
    const editor=vscode.window.activeTextEditor;
    if(!editor){vscode.window.showWarningMessage('Open a file and select code first');return;}
    if(editor.selection.isEmpty){vscode.window.showWarningMessage('Select the code to ask about');return;}
    const selected=editor.document.getText(editor.selection);
    if(selected.length>9000){vscode.window.showWarningMessage('Selection exceeds local context limit');return;}
    await vscode.commands.executeCommand('workbench.view.extension.agenticLocal');
    view.prefill('Explain this '+editor.document.languageId+' code and suggest improvements. Do not claim edits were applied.\\n\\n'+selected);
  }));
}
function deactivate() {}
module.exports.AgentPanel = AgentPanel;
module.exports={activate,deactivate};
