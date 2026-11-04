/* Build-time Monaco integration. Workers and CSS are served from localhost. */
import * as monaco from 'monaco-editor';
const editorElement = document.getElementById('editor');
const languageExtension = {
  py:'python',js:'javascript',jsx:'javascript',ts:'typescript',tsx:'typescript',
  json:'json',rs:'rust',go:'go',java:'java',sql:'sql',html:'html',htm:'html',
  css:'css',scss:'scss',c:'c',h:'cpp',cpp:'cpp',hpp:'cpp',md:'markdown',
  xml:'xml',yaml:'yaml',yml:'yaml',sh:'shell',bash:'shell',toml:'ini'
};
const language = () => {
  const filepath = document.getElementById('path')?.value ?? '';
  return languageExtension[filepath.split('.').pop().toLowerCase()] ?? 'plaintext';
};
self.MonacoEnvironment = {
  getWorkerUrl(_moduleId,label) {
    const worker = label === 'json' ? 'json.worker.js'
      : ['css','scss','less'].includes(label) ? 'css.worker.js'
      : ['html','handlebars','razor'].includes(label) ? 'html.worker.js'
      : ['javascript','typescript'].includes(label) ? 'ts.worker.js'
      : 'editor.worker.js';
    return '/assets/' + worker;
  }
};
if (editorElement) {
  const mount = document.createElement('div');
  mount.id = 'monaco-host';
  mount.style.cssText = 'flex:1;min-height:240px;width:100%;overflow:hidden';
  editorElement.parentNode.insertBefore(mount,editorElement);
  try {
    const editor = monaco.editor.create(mount,{
      value:editorElement.value,
      language:language(),
      theme:'vs-dark',
      automaticLayout:true,
      minimap:{enabled:false},
      inlineSuggest:{enabled:true},
      fontSize:13,
      tabSize:2,
      scrollBeyondLastLine:false,
      wordWrap:'off'
    });
    Object.defineProperty(editorElement,'value',{
      configurable:true,
      get:()=>editor.getValue(),
      set:value=>editor.setValue(String(value ?? ''))
    });
    editor.onDidChangeModelContent(()=>editorElement.dispatchEvent(new Event('input')));
    document.getElementById('path')?.addEventListener('input',()=>{
      monaco.editor.setModelLanguage(editor.getModel(),language());
    });
    editorElement.style.display='none';
    window.agenticMonacoEditor = editor;
    // Cursor-style ghost text: ask the local completion endpoint for the
    // missing text at the cursor. Silent on any failure, cancellable.
    const token = () => document.getElementById('token')?.value ?? '';
    monaco.languages.registerInlineCompletionItemProvider({pattern:'**'},{
      async provideInlineCompletionItems(model,position,_context,cancelToken){
        if(!token()) return {items:[]};
        const text = model.getValue();
        const offset = model.getOffsetAt(position);
        if(offset < 8) return {items:[]};
        const prefix = text.slice(Math.max(0,offset-4000),offset);
        const suffix = text.slice(offset,offset+1500);
        const controller = new AbortController();
        const cancel = cancelToken.onCancellationRequested(()=>controller.abort());
        const timer = setTimeout(()=>controller.abort(),9000);
        try {
          const response = await fetch('/api/ai/complete',{
            method:'POST',signal:controller.signal,
            headers:{'Content-Type':'application/json','Authorization':'Bearer '+token()},
            body:JSON.stringify({
              project:document.getElementById('project')?.value||'demo',
              path:document.getElementById('path')?.value||'',
              prefix,suffix,max_tokens:128,model:window.agenticModel||null
            })
          });
          if(!response.ok) return {items:[]};
          const data = await response.json();
          if(!data.completion||cancelToken.isCancellationRequested) return {items:[]};
          return {items:[{
            insertText:data.completion,
            range:new monaco.Range(position.lineNumber,position.column,
                                   position.lineNumber,position.column)
          }]};
        } catch(error) {
          return {items:[]};
        } finally {
          clearTimeout(timer);
          cancel.dispose();
        }
      }
    });
  } catch(error) {
    mount.remove();
    console.error('Local code editor startup failed; using native textarea.',error);
  }
}
