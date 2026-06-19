import { useRef, useState } from 'react';
import {
  AudioWaveform, Ban, CornerDownLeft, ImagePlus, Loader2, Mic,
  Sparkles, Volume2, VolumeX, X,
} from 'lucide-react';
import { useAppStore } from '../store';
import { useAppApi } from '../contexts/appApi';
import StatusBadge from './StatusBadge';
import { setConfigField } from '../lib/window';
import { toolLoadingLabel } from '../lib/tool_labels';

// 2026-06-19 · 图片输入(MVP)· 压图常量(按图计费硬限)
const IMG_MAX_LONG_EDGE = 1568;   // 长边(qwen-vl 推荐 ~1568)
const IMG_JPEG_QUALITY = 0.85;    // JPEG 0.85(截图小字可能糊 · PM watch · 真机调)
const IMG_MAX_BYTES = 2 * 1024 * 1024;  // 单张 ≤ 2MB(压完仍超 = 拒)
const IMG_MAX_COUNT = 4;          // 每条消息最多 4 张
const IMG_ACCEPT = 'image/png,image/jpeg,image/jpg,image/webp,image/gif';

/** File → 压图 base64 data URL · 失败抛 · 调用方 catch 显 toast。
 *  - HEIC / 解码失败 → image.onerror 抛(spec watch:优雅拒绝 · 别崩)
 *  - 等比缩到长边 ≤ IMG_MAX_LONG_EDGE · 走 JPEG 0.85
 *  - 输出 dataUrl/mime/bytes 给 store。 */
async function compressImage(file: File): Promise<{
  dataUrl: string; mime: string; bytes: number;
}> {
  // accept 已过滤 · 但保险检查
  if (!file.type.startsWith('image/')) {
    throw new Error(`不是图片(${file.type || 'unknown'})`);
  }
  const objectUrl = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error('图片解码失败(HEIC?换 jpg/png 试)'));
      el.src = objectUrl;
    });
    const longEdge = Math.max(img.naturalWidth, img.naturalHeight) || 1;
    const scale = longEdge > IMG_MAX_LONG_EDGE ? IMG_MAX_LONG_EDGE / longEdge : 1;
    const w = Math.round(img.naturalWidth * scale);
    const h = Math.round(img.naturalHeight * scale);
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('canvas 2d 上下文不可用');
    ctx.drawImage(img, 0, 0, w, h);
    const dataUrl = canvas.toDataURL('image/jpeg', IMG_JPEG_QUALITY);
    // base64 字节数 ≈ (length - prefix) * 3/4
    const b64 = dataUrl.split(',')[1] ?? '';
    const bytes = Math.floor((b64.length * 3) / 4);
    if (bytes > IMG_MAX_BYTES) {
      throw new Error(`压缩后仍 > 2MB(${Math.round(bytes / 1024)}KB)`);
    }
    return { dataUrl, mime: 'image/jpeg', bytes };
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

export default function ChatInput() {
  const [text, setText] = useState('');
  const [imgError, setImgError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const recording    = useAppStore((s) => s.recording);
  const micMuted     = useAppStore((s) => s.micMuted);
  const status       = useAppStore((s) => s.status);
  const recordingMode = useAppStore((s) => s.recordingMode);
  // 2026-06-05 · "真在听" 高亮:VAD 模式看 vadState · 手动模式看 recording。
  // 双源任一翻 truthy → 按钮点亮。手动话筒图标 + 点亮 = VAD 残留 active(bug)。
  const vadState     = useAppStore((s) => s.vadState);
  const ttsEnabled   = useAppStore((s) => s.ttsEnabled);
  const currentThinking = useAppStore((s) => s.currentThinking);
  const currentToolName = useAppStore((s) => s.currentToolName);

  // 2026-06-19 · 图片输入 MVP · store 队列 + 2 setter
  // clearAttachments 由 useWebSocket.sendText 内部调 · ChatInput 不直接用
  const pendingAttachments = useAppStore((s) => s.pendingAttachments);
  const addAttachment = useAppStore((s) => s.addAttachment);
  const removeAttachment = useAppStore((s) => s.removeAttachment);

  const { sendText, sendInterrupt, startManual, stopManualAndSend, toggleVad } = useAppApi();

  /** 接 N 个 File · 串行压图 · 失败 toast 单条提示。命中 IMG_MAX_COUNT 整批拒。 */
  const handleFiles = async (files: FileList | File[] | null) => {
    if (!files || files.length === 0) return;
    setImgError(null);
    const arr = Array.from(files);
    const currentCount = useAppStore.getState().pendingAttachments.length;
    if (currentCount + arr.length > IMG_MAX_COUNT) {
      setImgError(`最多 ${IMG_MAX_COUNT} 张 · 当前已 ${currentCount} 张`);
      return;
    }
    for (const f of arr) {
      try {
        const a = await compressImage(f);
        addAttachment(a);
      } catch (err) {
        const msg = (err as Error).message || '图片处理失败';
        setImgError(`${f.name}:${msg}`);
        console.warn('[ChatInput] image add failed', f.name, err);
        // 不 break · 继续处理后续文件
      }
    }
  };

  const onPickImages = () => {
    fileInputRef.current?.click();
  };

  const onFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    await handleFiles(e.target.files);
    // 同一文件再次选择不触发 onChange · reset
    e.target.value = '';
  };

  const onPaste = async (e: React.ClipboardEvent<HTMLInputElement>) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    const files: File[] = [];
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (it.kind === 'file' && it.type.startsWith('image/')) {
        const f = it.getAsFile();
        if (f) files.push(f);
      }
    }
    if (files.length === 0) return;
    // 阻止默认粘贴(否则会粘出文件名字符串到 input)
    e.preventDefault();
    await handleFiles(files);
  };

  const onDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const files = e.dataTransfer?.files;
    if (!files || files.length === 0) return;
    await handleFiles(files);
  };

  const onDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    // 允许 drop
    e.preventDefault();
  };

  const handleTts = () => {
    const next = !ttsEnabled;
    useAppStore.getState().setTtsEnabled(next);
    setConfigField('tts.enabled', next).catch((e) => {
      console.error('[TTS] sync config failed:', e);
      useAppStore.getState().setTtsEnabled(!next);
    });
  };

  const handleSend = () => {
    // pin 1:image-only 允许 · 文字非空 或 附件非空 都可发
    const trimmed = text.trim();
    const atts = useAppStore.getState().pendingAttachments;
    if (!trimmed && atts.length === 0) return;
    sendText(
      trimmed,
      atts.length > 0
        ? atts.map((a) => ({ dataUrl: a.dataUrl, mime: a.mime }))
        : undefined,
    );
    setText('');
    // sendText 内部已 clearAttachments() · 这里不重复(防 race)
  };

  const handleMic = async () => {
    if (micMuted) return;
    if (recordingMode === 'vad') {
      await toggleVad();
    } else {
      if (recording) {
        await stopManualAndSend();
      } else {
        await startManual();
      }
    }
  };

  const handleInterrupt = () => {
    // v3-F #4：真正打断 —— 后端取消 LLM stream + TTS，前端立即停播放
    sendInterrupt();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // 发送 enable 条件:文字非空 或 附件非空(pin 1)
  const canSend = text.trim().length > 0 || pendingAttachments.length > 0;

  return (
    <div
      className="flex flex-col gap-2 px-4 py-3 shrink-0"
      onDragOver={onDragOver}
      onDrop={onDrop}
      style={{
        // Round 4 ④(2026-06-04):吃 glass-* 统一 token · 删 rounded-2xl 改用
        // borderRadius var(--glass-radius) 让圆角跟所有浮件对齐(16px)。
        borderRadius: 'var(--glass-radius)',
        background: 'var(--glass-bg)',
        backdropFilter: 'blur(var(--glass-blur))',
        WebkitBackdropFilter: 'blur(var(--glass-blur))',
        border: 'var(--glass-border)',
        boxShadow: 'var(--glass-shadow)',
      }}
    >
      {/* 2026-06-19 · 图片输入 MVP · 缩略图行 + 删除 + 错误提示 ·
          这一行只在有附件或有 imgError 时渲染 · 不占空 */}
      {(pendingAttachments.length > 0 || imgError) && (
        <div className="flex flex-wrap items-center gap-2">
          {pendingAttachments.map((a) => (
            <div
              key={a.id}
              className="relative w-12 h-12 rounded-md overflow-hidden"
              style={{
                background: 'var(--color-bg-elevated)',
                border: '1px solid var(--color-border)',
              }}
              title={`${a.mime} · ${Math.round(a.bytes / 1024)} KB`}
            >
              <img
                src={a.dataUrl}
                alt="attachment"
                className="w-full h-full object-cover"
                draggable={false}
              />
              <button
                type="button"
                onClick={() => removeAttachment(a.id)}
                className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full flex items-center justify-center"
                style={{
                  background: 'rgba(0, 0, 0, 0.6)',
                  color: '#fff',
                }}
                title="移除"
              >
                <X size={10} />
              </button>
            </div>
          ))}
          {pendingAttachments.length > 0 && (
            <span className="text-[10px]"
                  style={{ color: 'var(--color-text-secondary)' }}>
              {pendingAttachments.length} / {IMG_MAX_COUNT}
            </span>
          )}
          {imgError && (
            <span className="text-[10px]"
                  style={{ color: 'rgb(239, 68, 68)' }}>
              {imgError}
            </span>
          )}
        </div>
      )}
      <div className="flex items-center gap-2">
      <StatusBadge status={status} />

      {/* v3-F #4: 打断按钮 —— thinking / speaking 时可按 */}
      <button
        className="w-9 h-9 rounded-full flex items-center justify-center transition disabled:opacity-30 disabled:cursor-not-allowed"
        style={{
          background: 'color-mix(in srgb, var(--color-bg-elevated) 80%, transparent)',
          color: 'var(--color-text-secondary)',
        }}
        onClick={handleInterrupt}
        disabled={status !== 'speaking' && status !== 'thinking'}
        title="打断"
      >
        <Ban size={18} />
      </button>

      {/* v3-F: AI 内心独白。仅当本轮收到 thinking 时显示，下一轮发送清空 */}
      {currentThinking && (
        <div
          className="flex items-center gap-1.5 rounded-full px-3 py-1 text-xs italic max-w-[280px] overflow-hidden text-ellipsis whitespace-nowrap"
          style={{
            background: 'color-mix(in srgb, var(--color-accent) 18%, transparent)',
            color: 'var(--color-text-accent)',
            border: '1px solid color-mix(in srgb, var(--color-accent) 30%, transparent)',
          }}
          title={currentThinking}
        >
          <Sparkles size={12} className="shrink-0" />
          <span className="truncate">{currentThinking}</span>
        </div>
      )}

      {/* UX-004: tool loading indicator。LLM 调 tool 期间显示前缀 mapping 文案
          (查日历… / 查歌单… / etc),fallback "查询中…"。LLM 若遵守 prompt
          先输出过渡语,此 indicator 与过渡语并存形成"语言 + 视觉"双重反馈;
          LLM 不遵守时此 indicator 兜底视觉反馈。tool_use_done 时由 store
          自动清空。 */}
      {currentToolName && (
        <div
          className="flex items-center gap-1.5 rounded-full px-3 py-1 text-xs animate-pulse max-w-[220px] overflow-hidden text-ellipsis whitespace-nowrap"
          style={{
            background: 'color-mix(in srgb, var(--color-bg-elevated) 60%, transparent)',
            color: 'var(--color-text-secondary)',
            border: '1px dashed var(--color-border-subtle)',
          }}
          title={`tool: ${currentToolName}`}
        >
          <Loader2 size={12} className="shrink-0 animate-spin" />
          <span className="truncate">{toolLoadingLabel(currentToolName)}</span>
        </div>
      )}
      {/* 2026-06-19 · 图片输入 MVP · 选图按钮 + hidden file input ·
          点击 = 文件选择;支持拖拽到整个 root(onDrop)+ input 粘贴(onPaste) */}
      <input
        ref={fileInputRef}
        type="file"
        accept={IMG_ACCEPT}
        multiple
        onChange={onFileChange}
        style={{ display: 'none' }}
      />
      <button
        className="w-9 h-9 rounded-full flex items-center justify-center transition disabled:opacity-30 disabled:cursor-not-allowed"
        style={{
          background: 'color-mix(in srgb, var(--color-bg-elevated) 80%, transparent)',
          color: pendingAttachments.length > 0
            ? 'var(--color-text-accent)'
            : 'var(--color-text-secondary)',
        }}
        onClick={onPickImages}
        disabled={pendingAttachments.length >= IMG_MAX_COUNT}
        title={
          pendingAttachments.length >= IMG_MAX_COUNT
            ? `已达上限 ${IMG_MAX_COUNT} 张`
            : '加图片(拖拽 / 粘贴 / 选择)'
        }
      >
        <ImagePlus size={18} />
      </button>

      {/* Text field · onPaste 抓图(从剪贴板) */}
      <input
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        onPaste={onPaste}
        placeholder="输入消息(可拖图 / 粘贴 / 选图)…"
        className="flex-1 rounded-xl px-4 py-2 text-sm outline-none focus:ring-1"
        style={{
          background: 'var(--color-bg-input)',
          color: 'var(--color-text-primary)',
        }}
      />

      {/* Send · pin 1:image-only 允许 · canSend = text 或 attachments */}
      <button
        className="w-9 h-9 rounded-full flex items-center justify-center transition disabled:opacity-30 disabled:cursor-not-allowed"
        style={{
          background: canSend ? 'var(--color-accent)' : 'var(--color-bg-elevated)',
          color: canSend ? 'var(--color-bubble-user-text)' : 'var(--color-text-primary)',
        }}
        onClick={handleSend}
        disabled={!canSend}
        title="发送"
      >
        <CornerDownLeft size={18} />
      </button>

      {/* Mic · 2026-06-05 · 图标按 recordingMode 切(手动=话筒/VAD=波形) ·
          点亮 = "真在听":手动看 recording、VAD 看 vadState∈{active,recording} ·
          手动按钮 + 点亮 = silero 残留 active 的 bug 信号 */}
      {(() => {
        const isVad = recordingMode === 'vad';
        const isListening = isVad
          ? (vadState === 'active' || vadState === 'recording')
          : recording;
        const Icon = isVad ? AudioWaveform : Mic;
        const titleListening = isVad ? '停止监听' : '停止录音';
        const titleIdle      = isVad ? '开始监听' : '开始录音';
        return (
          <button
            className="w-9 h-9 rounded-full flex items-center justify-center transition disabled:opacity-40 disabled:cursor-not-allowed"
            style={
              isListening
                ? { background: 'var(--color-accent)', color: 'var(--color-bubble-user-text)' }
                : {
                    background: 'color-mix(in srgb, var(--color-bg-elevated) 80%, transparent)',
                    color: 'var(--color-text-primary)',
                  }
            }
            onClick={handleMic}
            disabled={micMuted}
            title={isListening ? titleListening : titleIdle}
            aria-label={isListening ? titleListening : titleIdle}
            aria-pressed={isListening}
          >
            <Icon size={18} />
          </button>
        );
      })()}

      {/* TTS toggle */}
      <button
        className="w-9 h-9 rounded-full flex items-center justify-center transition"
        style={
          ttsEnabled
            ? {
                background: 'color-mix(in srgb, var(--color-accent) 35%, transparent)',
                color: 'var(--color-text-accent)',
              }
            : {
                background: 'color-mix(in srgb, var(--color-bg-elevated) 80%, transparent)',
                color: 'var(--color-text-secondary)',
              }
        }
        onClick={handleTts}
        title={ttsEnabled ? 'TTS 已开启' : 'TTS 已关闭'}
      >
        {ttsEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />}
      </button>
      </div>
    </div>
  );
}
