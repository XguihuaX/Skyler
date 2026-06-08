import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// cut · 进入动画"小窗→大窗"闪修法:
//   Tauri 默认 350×500 widget · React mount 后 App.tsx useEffect 才 async 调
//   applyModeWindowProps resize 到 1100×750 panel · 用户看到~300-500ms 小窗
//   先出再变大。这里在 React render 之前先 await Tauri setSize 完成,Tauri
//   窗口直接以正确 mode 大小起,LoadingScreen 一上来就是终态大小。
//
//   纯浏览器 dev(无 Tauri)applyModeWindowProps 会 throw · try/catch 吞 ·
//   仍渲染 React。App.tsx 的 mount useEffect 同套 resize 保留作 safety net,
//   幂等(同 size 时 Tauri setSize 是 no-op cost)。
async function bootstrap(): Promise<void> {
  try {
    const raw = localStorage.getItem('momoos.mode')
    const mode: 'widget' | 'panel' =
      raw === 'widget' || raw === 'panel' ? raw : 'panel'
    const { applyModeWindowProps } = await import('./lib/window')
    await applyModeWindowProps(mode)
  } catch (e) {
    console.warn('[main] pre-mount applyModeWindowProps failed (非 Tauri?):', e)
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}
void bootstrap()
