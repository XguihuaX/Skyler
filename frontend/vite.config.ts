import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteStaticCopy } from 'vite-plugin-static-copy'

// INV-17 v3.3 (2026-05-28): silero VAD + onnxruntime-web 自托管 · 走 maintainer
// 推荐 vite-plugin-static-copy。原 public/silero/ 路线 + scripts/copy-silero-assets.mjs
// 因 vite "files in /public should not be imported from source code" 规则在 ort
// dynamic import('.../*.mjs') 时 500 · 改用此 plugin · dev 中间件 + build copy
// 都绕过 public/ 限制。targets dest 维持 silero/ + silero/ort/ namespace · 跟
// useAudio.ts MicVAD.new({ baseAssetPath: '/silero/', onnxWASMBasePath: '/silero/ort/' })
// 对齐。silero_vad_v5.onnx 不复制(INV-17 v3 decision #8: legacy 唯一)。
// Sources: https://docs.vad.ricky0123.com/user-guide/browser/
//          https://docs.vad.ricky0123.com/user-guide/api/
export default defineConfig({
  plugins: [
    react(),
    viteStaticCopy({
      // v4 默认保留完整 src 目录结构(node_modules/.../dist/*)· 用
      // rename.stripBase: true 强制 flat copy · 让文件直接落在 dest 根下。
      targets: [
        { src: 'node_modules/@ricky0123/vad-web/dist/vad.worklet.bundle.min.js', dest: 'silero',     rename: { stripBase: true } },
        { src: 'node_modules/@ricky0123/vad-web/dist/silero_vad_legacy.onnx',    dest: 'silero',     rename: { stripBase: true } },
        { src: 'node_modules/onnxruntime-web/dist/*.wasm',                       dest: 'silero/ort', rename: { stripBase: true } },
        { src: 'node_modules/onnxruntime-web/dist/*.mjs',                        dest: 'silero/ort', rename: { stripBase: true } },
      ],
    }),
  ],
})
