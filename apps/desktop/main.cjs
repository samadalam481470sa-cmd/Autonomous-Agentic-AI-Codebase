const {app,BrowserWindow,dialog}=require('electron');
const path=require('node:path');
const fs=require('node:fs');
const os=require('node:os');
const crypto=require('node:crypto');
const {spawn}=require('node:child_process');
const http=require('node:http');
const SERVER='http://127.0.0.1:8000';
let win,backend,starting=false;
function backendPath(){
 const exe=process.platform==='win32'?'agentic-backend.exe':'agentic-backend';
 return app.isPackaged?path.join(process.resourcesPath,'backend','agentic-backend',exe):path.resolve(__dirname,'../../dist/backend/agentic-backend',exe);
}
function checkReady(){
 return new Promise(resolve=>{
  const req=http.get(SERVER+'/openapi.json',{timeout:1000},res=>{res.resume();resolve(res.statusCode===200)});
  req.on('error',()=>resolve(false));req.on('timeout',()=>{req.destroy();resolve(false)});
 });
}
async function startBackend(){
 if(starting)return;starting=true;
 const binary=backendPath();
 if(!fs.existsSync(binary)){dialog.showErrorBox('Backend missing','Bundled Python backend not found: '+binary);return}
 if(await checkReady()){dialog.showErrorBox('Port already occupied','Another service is listening on port 8000. Stop it before launching this desktop app.');return}
 const data=path.join(app.getPath('userData'),'local-data');
 fs.mkdirSync(data,{recursive:true});
 const token=crypto.randomBytes(32).toString('hex');
 backend=spawn(binary,[],{cwd:data,windowsHide:true,stdio:'ignore',env:{...process.env,AGENT_ADMIN_TOKEN:token,WORKSPACE_ROOT:path.join(data,'workspaces'),DB_PATH:path.join(data,'agent.sqlite3'),LOCAL_MODEL_ONLY:'1',LOCAL_MODEL_BASE_URL:'http://127.0.0.1:8088/v1',LOCAL_MODEL_NAME:process.env.LOCAL_MODEL_NAME||'local-model'}});
 backend.on('error',e=>dialog.showErrorBox('Backend error',e.message));
 let ready=false;
 for(let i=0;i<60;i++){
  if(backend.exitCode!==null)break;
  if(await checkReady()){ready=true;break}
  await new Promise(r=>setTimeout(r,500));
 }
 if(!ready){dialog.showErrorBox('Backend startup failed','Check that port 8000 is free and that the backend is compatible with this OS.');return}
 await create(token);
}
async function create(token){
 win=new BrowserWindow({width:1440,height:920,minWidth:900,minHeight:620,backgroundColor:'#0c1220',webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,preload:path.join(__dirname,'preload.cjs')}});
 win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
 win.webContents.on('will-navigate',(event,url)=>{if(!url.startsWith(SERVER+'/'))event.preventDefault()});
 win.webContents.session.setPermissionRequestHandler((_wc,_permission,callback)=>callback(false));
 await win.loadURL(SERVER+'/studio');
 win.webContents.executeJavaScript("document.getElementById('token').value="+JSON.stringify(token)+";document.getElementById('refresh').click();");
}
app.whenReady().then(startBackend);
app.on('before-quit',()=>{if(backend&&!backend.killed)backend.kill()});
app.on('window-all-closed',()=>{if(process.platform!=='darwin')app.quit()});
app.on('activate',()=>{if(BrowserWindow.getAllWindows().length===0&&!starting)startBackend()});
