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
  } catch(error) {
    mount.remove();
    console.error('Local code editor startup failed; using native textarea.',error);
  }
}
