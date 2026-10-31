const vscode=require('vscode');
function activate(context){
 for(const [name,path] of [['openStudio','/studio'],['openChat','/']]){
  context.subscriptions.push(vscode.commands.registerCommand('autonomousAI.'+name,async()=>{
   const panel=vscode.window.createWebviewPanel('autonomousAI','Autonomous Agentic AI',vscode.ViewColumn.Beside,{enableScripts:false});
   panel.webview.html='<html><body style="font:14px system-ui;background:#111827;color:#fff;padding:24px"><h2>Autonomous Agentic AI</h2><p>Open the local coding workspace in your browser. The backend must be running.</p><p><a href="http://127.0.0.1:8000'+path+'">Open local workspace</a></p></body></html>';
   await vscode.env.openExternal(vscode.Uri.parse('http://127.0.0.1:8000'+path));
  }));
 }
}
function deactivate(){}
module.exports={activate,deactivate};
