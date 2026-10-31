const {app,BrowserWindow,dialog,ipcMain}=require('electron');
const path=require('node:path');
const fs=require('node:fs');
const os=require('node:os');
const crypto=require('node:crypto');
const {spawn}=require('node:child_process');
const http=require('node:http');
const https=require('node:https');
const {pipeline}=require('node:stream/promises');
const SERVER='http://127.0.0.1:8000';
let win,backend,modelServer,rustGateway,starting=false,adminToken='';
function backendPath(){
 const exe=process.platform==='win32'?'agentic-backend.exe':'agentic-backend';
 return app.isPackaged?path.join(process.resourcesPath,'backend',exe):path.resolve(__dirname,'../../dist/backend',exe);
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
 adminToken=token;
 backend=spawn(binary,[],{cwd:data,windowsHide:true,stdio:'ignore',env:{...process.env,AGENT_ADMIN_TOKEN:token,WORKSPACE_ROOT:path.join(data,'workspaces'),DB_PATH:path.join(data,'agent.sqlite3'),PROJECT_DB_PATH:path.join(data,'projects.sqlite3'),LOCAL_MODEL_ONLY:'1',LOCAL_MODEL_BASE_URL:'http://127.0.0.1:8088/v1',LOCAL_MODEL_NAME:process.env.LOCAL_MODEL_NAME||'local-model'}});
 backend.on('error',e=>dialog.showErrorBox('Backend error',e.message));
 let ready=false;
 for(let i=0;i<60;i++){
  if(backend.exitCode!==null)break;
  if(await checkReady()){ready=true;break}
  await new Promise(r=>setTimeout(r,500));
 }
 if(!ready){dialog.showErrorBox('Backend startup failed','Check that port 8000 is free and that the backend is compatible with this OS.');return}
 await setupWindow();
}
async function create(token){
 win=new BrowserWindow({width:1440,height:920,minWidth:900,minHeight:620,backgroundColor:'#0c1220',webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,preload:path.join(__dirname,'preload.cjs')}});
 win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
 win.webContents.on('will-navigate',(event,url)=>{if(!url.startsWith(SERVER+'/'))event.preventDefault()});
 win.webContents.session.setPermissionRequestHandler((_wc,_permission,callback)=>callback(false));
 await win.loadURL(SERVER+'/studio');
 await win.webContents.executeJavaScript("document.getElementById('token').value="+JSON.stringify(token)+";document.getElementById('refresh').click();");
}
function runtimeBinary(){
 const name=process.platform==='win32'?'agentic-runtime.exe':'agentic-runtime';
 return app.isPackaged?path.join(process.resourcesPath,'backend',name):path.resolve(__dirname,'../../dist/backend',name);
}
async function setupWindow(){
 win=new BrowserWindow({width:900,height:680,backgroundColor:'#0c1220',webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,preload:path.join(__dirname,'preload.cjs')}});
 win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
 await win.loadFile(path.join(__dirname,'setup.html'));
}
function requireSetup(event){
 const sender=BrowserWindow.fromWebContents(event.sender);
 if(!sender||sender!==win||!event.sender.getURL().startsWith('file://')||!event.sender.getURL().endsWith('/setup.html'))throw new Error('Setup-only action');
}
function trustedModelURL(value){
 const u=new URL(value);
 const h=u.hostname.toLowerCase();
 if(u.protocol!=='https:'||u.username||u.password||u.port||!(h==='huggingface.co'||h.endsWith('.huggingface.co')||h==='hf.co'||h.endsWith('.hf.co')||h.endsWith('.xethub.hf.co')))throw new Error('Only trusted Hugging Face HTTPS download URLs are supported');
 return u;
}
async function requestModel(url,redirects=0){
 if(redirects>6)throw new Error('Too many redirects');
 const u=trustedModelURL(url);
 return new Promise((resolve,reject)=>{
  const req=https.get(u,{timeout:30000,headers:{'User-Agent':'Autonomous-Agentic-AI/0.3'}},res=>{
   if([301,302,303,307,308].includes(res.statusCode)){
    const location=res.headers.location;
    res.resume();
    if(!location)return reject(new Error('Redirect missing location'));
    return resolve(requestModel(new URL(location,u).toString(),redirects+1));
   }
   if(res.statusCode!==200){res.resume();return reject(new Error('Model download HTTP '+res.statusCode))}
   resolve(res);
  });
  req.on('timeout',()=>req.destroy(new Error('Download timed out')));
  req.on('error',reject);
 });
}
ipcMain.handle('download-model',async (event,details)=>{
 requireSetup(event);
 if(!details||details.licenseAccepted!==true)throw new Error('Confirm model license and download permission');
 if(typeof details.url!=='string'||typeof details.sha256!=='string'||!/^[a-f0-9]{64}$/i.test(details.sha256))throw new Error('A valid HTTPS URL and SHA256 checksum are required');
 const url=trustedModelURL(details.url);
 if(!url.pathname.toLowerCase().endsWith('.gguf'))throw new Error('Download URL must point to a .gguf file');
 const dir=path.join(app.getPath('userData'),'models');fs.mkdirSync(dir,{recursive:true});
 const destination=path.join(dir,details.sha256.toLowerCase()+'.gguf');
 if(fs.existsSync(destination))return destination;
 const temporary=destination+'.partial-'+crypto.randomBytes(6).toString('hex');
 let total=0;const hash=crypto.createHash('sha256');
 try{
  const stream=await requestModel(url.toString());
  const writer=fs.createWriteStream(temporary,{flags:'wx',mode:0o600});
  stream.on('data',chunk=>{
   total+=chunk.length;
   if(total>20*1024*1024*1024)stream.destroy(new Error('Model exceeds 20 GB limit'));
   hash.update(chunk);
  });
  await pipeline(stream,writer);
  if(hash.digest('hex')!==details.sha256.toLowerCase())throw new Error('SHA256 checksum mismatch');
  fs.renameSync(temporary,destination);
  return destination;
 }catch(e){try{fs.unlinkSync(temporary)}catch(_){}throw e}
});
ipcMain.handle('choose-file',async (event,kind)=>{
 requireSetup(event);
 if(kind!=='model'&&kind!=='engine')throw new Error('Invalid file type');
 const result=await dialog.showOpenDialog(win,{properties:['openFile'],filters:kind==='model'?[{name:'GGUF model',extensions:['gguf']}]:[]});
 return result.canceled?null:result.filePaths[0];
});
ipcMain.handle('hardware',async(event)=>{
 requireSetup(event);
 const result={platform:process.platform,architecture:process.arch,cpus:os.cpus().length,memoryGB:Math.round(os.totalmem()/1073741824)};
 if(process.platform==='darwin'&&process.arch==='arm64')result.gpu='Apple Silicon / Metal may be available';
 else result.gpu='Check vendor drivers and GPU compatibility';
 return result;
});
function waitFor(url,timeoutMs=120000){
 return new Promise(async(resolve,reject)=>{
  const started=Date.now();
  while(Date.now()-started<timeoutMs){
   try{
    const ready=await new Promise(done=>{
     const request=http.get(url,{timeout:1500},r=>{r.resume();done(r.statusCode===200)});
     request.on('error',()=>done(false));request.on('timeout',()=>{request.destroy();done(false)});
    });
    if(ready)return resolve();
   }catch(_){}
   await new Promise(r=>setTimeout(r,500));
  }
  reject(new Error('Local service did not become ready: '+url));
 });
}
ipcMain.handle('start-model',async (event,settings)=>{
 requireSetup(event);
 if(modelServer||rustGateway)throw new Error('Model is already starting');
 if(!settings||typeof settings.model!=='string'||typeof settings.engine!=='string')throw new Error('Choose model and inference engine');
 const model=path.resolve(settings.model),engine=path.resolve(settings.engine);
 if(path.extname(model).toLowerCase()!=='.gguf'||!fs.statSync(model).isFile()||!fs.statSync(engine).isFile())throw new Error('Select valid model and engine files');
 const layers=Number(settings.layers);
 if(!Number.isInteger(layers)||layers<0||layers>999)throw new Error('Invalid GPU layer count');
 const rust=runtimeBinary();
 if(!fs.existsSync(rust))throw new Error('Bundled Rust gateway missing');
 try{
  modelServer=spawn(engine,['-m',model,'--host','127.0.0.1','--port','9931','-c','4096','-ngl',String(layers),'--jinja','--alias','local-model'],{windowsHide:true,stdio:'ignore'});
  await waitFor('http://127.0.0.1:9931/v1/models');
  rustGateway=spawn(rust,['serve'],{windowsHide:true,stdio:'ignore',env:{...process.env,LLAMA_UPSTREAM:'http://127.0.0.1:9931/v1'}});
  await waitFor('http://127.0.0.1:8088/health');
  return {ok:true};
 }catch(e){
  if(rustGateway){rustGateway.kill();rustGateway=null}
  if(modelServer){modelServer.kill();modelServer=null}
  throw e;
 }
});
ipcMain.handle('open-studio',async(event)=>{requireSetup(event);const old=win;await create(adminToken);if(old&&!old.isDestroyed())old.close();return true});
app.whenReady().then(startBackend);
app.on('before-quit',()=>{for(const p of [rustGateway,modelServer,backend])if(p&&!p.killed)p.kill()});
app.on('window-all-closed',()=>{if(process.platform!=='darwin')app.quit()});
app.on('activate',()=>{if(BrowserWindow.getAllWindows().length===0)setupWindow()});
