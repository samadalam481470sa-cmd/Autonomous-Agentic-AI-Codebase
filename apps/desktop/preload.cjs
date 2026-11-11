const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('localSetup',Object.freeze({
 chooseModel:()=>ipcRenderer.invoke('choose-file','model'),
 checkModelLicense:details=>ipcRenderer.invoke('check-model-license',details),
 downloadModel:details=>ipcRenderer.invoke('download-model',details),
 chooseEngine:()=>ipcRenderer.invoke('choose-file','engine'),
 hardware:()=>ipcRenderer.invoke('hardware'),
 probeEngine:file=>ipcRenderer.invoke('probe-engine',file),
 startModel:settings=>ipcRenderer.invoke('start-model',settings),
 getAlwaysOn:()=>ipcRenderer.invoke('get-always-on'),
 setAlwaysOn:enabled=>ipcRenderer.invoke('set-always-on',enabled===true),
 openStudio:()=>ipcRenderer.invoke('open-studio')
}));
