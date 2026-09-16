// src/main/preload.ts
// 预加载脚本的旧位置版本（历史遗留）：当前 electron-vite 实际构建的是 src/preload/index.ts，
// 见 electron/electron.vite.config.ts 的 preload.build.lib.entry。
// 保留本文件仅作参考，修改桌面能力时请改 src/preload/index.ts，两者不要各改一半。
// Electron 预加载 API：contextBridge 把白名单对象挂到页面 window 上，ipcRenderer 负责调用主进程通道
import { contextBridge, ipcRenderer } from 'electron';

// 暴露一个安全的 API 给渲染进程
// 挂载名是 'electronAPI'（注意：src/preload/index.ts 用的是 'desktop'，两者命名并不一致）
contextBridge.exposeInMainWorld('electronAPI', {
    /**
     * 弹出系统原生文件夹选择框，走主进程注册的 `dialog:selectFolder` 通道。
     * @returns 选中的文件夹绝对路径；用户取消或窗口不存在时为 null
     */
    selectFolder: (): Promise<string | null> => {
        return ipcRenderer.invoke('dialog:selectFolder');
    },
});
