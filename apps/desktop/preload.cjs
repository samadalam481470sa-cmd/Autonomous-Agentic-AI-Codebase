const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('localSetup',Object.freeze({
 chooseModel:()=>ipcRenderer.invoke('choose-file','model'),
 downloadModel:details=>ipcRenderer.invoke('download-model',details),
 chooseEngine:()=>ipcRenderer.invoke('choose-file','engine'),
 hardware:()=>ipcRenderer.invoke('hardware'),
 startModel:settings=>ipcRenderer.invoke('start-model',settings),
 openStudio:()=>ipcRenderer.invoke('open-studio')
}));
