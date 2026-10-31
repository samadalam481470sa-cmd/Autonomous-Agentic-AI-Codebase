const {app,BrowserWindow,shell,dialog}=require('electron');
const path=require('node:path');
const SERVER='http://127.0.0.1:8000';
let win;
function create(){
 win=new BrowserWindow({width:1440,height:920,minWidth:900,minHeight:620,backgroundColor:'#0c1220',webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,preload:path.join(__dirname,'preload.cjs')}});
 win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
 win.webContents.on('will-navigate',(event,url)=>{if(!url.startsWith(SERVER+'/'))event.preventDefault()});
 win.webContents.session.setPermissionRequestHandler((_wc,_permission,callback)=>callback(false));
 win.loadURL(SERVER+'/studio').catch(()=>dialog.showErrorBox('Local server unavailable','Start the Python backend on 127.0.0.1:8000 before launching the desktop client.'));
}
app.whenReady().then(create);
app.on('window-all-closed',()=>{if(process.platform!=='darwin')app.quit()});
app.on('activate',()=>{if(BrowserWindow.getAllWindows().length===0)create()});
