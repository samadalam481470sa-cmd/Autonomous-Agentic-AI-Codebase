'use strict';
const crypto=require('node:crypto');
const {localEndpoint}=require('./sse.js');

function digest(content) {
  return crypto.createHash('sha256').update(content,'utf8').digest('hex');
}
function unchanged(document,selection,version,old) {
  return !document.isClosed && document.version===version && document.getText(selection)===old;
}
async function rewriteSelection(vscode,context,secretKey) {
  const editor=vscode.window.activeTextEditor;
  if (!editor || editor.selection.isEmpty) {
    vscode.window.showWarningMessage('Select some code in your editor first.');return;
  }
  if(!vscode.workspace.isTrusted) {
    vscode.window.showWarningMessage('Trust this workspace before using local AI edits.');return;
  }
  const document=editor.document;
  const selection=new vscode.Selection(editor.selection.start,editor.selection.end);
  const original=document.getText(selection),version=document.version;
  if (!original || original.length>12000 || document.uri.scheme!=='file') {
    vscode.window.showWarningMessage('Select up to 12,000 characters in a local file.');return;
  }
  const instruction=await vscode.window.showInputBox({
    title:'Local AI · Rewrite Selection',
    prompt:'Describe the change. No file edits occur until you approve.',
    validateInput: value=>value.trim().length<4?'Enter a more specific instruction':null,
    ignoreFocusOut:true
  });
  if(!instruction)return;
  if(!unchanged(document,selection,version,original)) {
    vscode.window.showWarningMessage('Selection changed. Please request a new rewrite.');return;
  }
  const token=await context.secrets.get(secretKey);
  if(!token){vscode.window.showWarningMessage('Connect Local AI before editing.');return;}
  let endpoint;
  try {endpoint=localEndpoint(vscode.workspace.getConfiguration('agenticLocal').get('endpoint','http://127.0.0.1:8000'));}
  catch(e){vscode.window.showErrorMessage(e.message);return;}
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),120000);
  let proposal;
  try {
    const r=await fetch(endpoint+'/api/ide/rewrite',{
      method:'POST',redirect:'error',signal:controller.signal,
      headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},
      body:JSON.stringify({language:document.languageId||'plaintext',selection:original,instruction})
    });
    if(!r.ok)throw Error('Local rewrite HTTP '+r.status);
    proposal=await r.json();
    if(!proposal || proposal.requires_approval!==true || typeof proposal.content!=='string'
       || proposal.content.length>50000 || proposal.source_sha256!==digest(original))
       throw Error('Model returned an invalid proposal');
  }catch(e){vscode.window.showErrorMessage('Local AI rewrite failed: '+String(e.message||e));return;}
  finally{clearTimeout(timeout);}
  if(proposal.content===original || !proposal.changed) {
    vscode.window.showInformationMessage('No change was suggested.');return;
  }
  if(!unchanged(document,selection,version,original)){
    vscode.window.showWarningMessage('Source changed while the model generated a rewrite.');return;
  }
  const left=await vscode.workspace.openTextDocument({language:document.languageId,content:original});
  const right=await vscode.workspace.openTextDocument({language:document.languageId,content:proposal.content});
  await vscode.commands.executeCommand('vscode.diff',left.uri,right.uri,'Local AI · Review Replacement',{preview:true});
  const decision=await vscode.window.showInformationMessage(
    'Apply the reviewed AI replacement to the original selected code?',
    {modal:true},'Apply Selection'
  );
  if(decision!=='Apply Selection')return;
  if(!unchanged(document,selection,version,original)) {
    vscode.window.showErrorMessage('Source changed since review; rewrite rejected.');return;
  }
  const edit=new vscode.WorkspaceEdit();
  edit.replace(document.uri,selection,proposal.content);
  const applied=await vscode.workspace.applyEdit(edit);
  if(applied)vscode.window.showInformationMessage('Approved edit applied (undoable). Save the file when ready.');
  else vscode.window.showErrorMessage('Editor did not accept the proposed replacement.');
}
module.exports={rewriteSelection,digest,unchanged};
