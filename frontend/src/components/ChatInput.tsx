import { useLayoutEffect, useRef, useState } from 'react';
import {
  ArrowUp, AudioWaveform, Brain, ChevronDown, ChevronUp, FileText, Globe,
  ImagePlus, Loader2, Mic, Paperclip, Sparkles, Volume2, VolumeX, X,
} from 'lucide-react';
import { useAppStore, type AiStatus } from '../store';
import { useAppApi } from '../contexts/appApi';
import { setConfigField } from '../lib/window';
import { toggleConfigField } from '../lib/toggleConfig';
import { toolLoadingLabel } from '../lib/tool_labels';

// 2026-06-19 · Build 1 决策 ① · 微型 AI 状态指示(取代大 StatusBadge)·
// idle 时整个 null · 非 idle 才显小色点 + 极短标签 · 进簇2 活动类。
// 不动左栏 ConnectionDot(那连的是 WS 连接 · 跟 AiStatus 正交)。
const aiStatusConfig: Record<Exclude<AiStatus, 'idle'>, { label: string; color: string }> = {
  listening:   { label: '聆听', color: 'var(--color-accent)' },
  thinking:    { label: '思考', color: '#F59E0B' },  // amber-500
  speaking:    { label: '说话', color: '#10B981' },  // emerald-500
  interrupted: { label: '已断', color: '#F43F5E' },  // rose-500
};
function StatusMicro({ status }: { status: AiStatus }) {
  if (status === 'idle') return null;
  const { label, color } = aiStatusConfig[status];
  return (
    <span
      className="inline-flex items-center gap-1 text-[11px]"
      style={{ color: 'var(--color-text-secondary)' }}
      title={`AI: ${label}`}
    >
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: color }}
      />
      {label}
    </span>
  );
}

// 2026-06-19 · 图片输入(MVP)· 压图常量(按图计费硬限)
const IMG_MAX_LONG_EDGE = 1568;   // 长边(qwen-vl 推荐 ~1568)
const IMG_JPEG_QUALITY = 0.85;    // JPEG 0.85(截图小字可能糊 · PM watch · 真机调)
const IMG_MAX_BYTES = 2 * 1024 * 1024;  // 单张图 ≤ 2MB(压完仍超 = 拒)
const IMG_MAX_COUNT = 4;          // 每条消息最多 4 张(image + file 共用总数 · 锁定 3)
const IMG_ACCEPT = 'image/png,image/jpeg,image/jpg,image/webp,image/gif';

// 2026-06-19 · 文件输入(MVP)· 文档常量(锁定 2:txt/md/code + docx + pdf)
const FILE_MAX_BYTES = 10 * 1024 * 1024;   // 单文件 ≤ 10MB(锁定 6)
const TOTAL_MAX_BYTES = 10 * 1024 * 1024;  // 所有 attachments 原字节总和 ≤ 10MB
                                            // (补丁 A · uvicorn ws_max_size 默认 16MB
                                            //  base64 膨胀 ~4/3 · 10MB 原字节 ≈ 13.3MB
                                            //  稳在 16MB 内)
const DOC_ACCEPT =
  '.txt,.md,.markdown,.rst,' +
  '.py,.ts,.tsx,.js,.jsx,.mjs,.cjs,' +
  '.json,.yaml,.yml,.toml,.ini,.cfg,' +
  '.sh,.bash,' +
  '.html,.htm,.css,.scss,' +
  '.go,.rs,.java,.kt,.swift,' +
  '.c,.cpp,.cc,.cxx,.h,.hpp,' +
  '.rb,.php,.lua,.pl,' +
  '.sql,.csv,.tsv,.xml,.log,' +
  '.vue,.svelte,' +
  '.pdf,.docx,' +
  'text/plain,text/markdown,application/pdf,' +
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
const ACCEPT_ALL = IMG_ACCEPT + ',' + DOC_ACCEPT;

// 2026-06-19 · 输入框重构 · textarea 自增长上限(5-6 行后内部滚动)
// 真值用 line-height × MAX_LINES + 上下 padding 算 · 防 hard-code px 跟主题脱节
const TEXTAREA_MAX_LINES = 6;

/** 2026-06-19 · 文件输入(MVP)· File → base64 data URL · 不压缩。
 *  跟 compressImage 平级 · ChatInput::handleFiles 按 mime 分派。
 *  - mime 可能是 application/octet-stream / 空(代码文件)· 透传原值
 *  - 后端 ws.py + file_extract.is_supported 用 mime + 扩展名兜底再校验 */
async function readFileAsDataUrl(file: File): Promise<{
  dataUrl: string; mime: string; bytes: number; filename: string;
}> {
  if (file.size > FILE_MAX_BYTES) {
    throw new Error(`文件 > ${FILE_MAX_BYTES / 1024 / 1024}MB`);
  }
  const dataUrl: string = await new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(typeof r.result === 'string' ? r.result : '');
    r.onerror = () => reject(new Error('文件读取失败'));
    r.readAsDataURL(file);
  });
  if (!dataUrl) throw new Error('文件读取失败:空');
  return {
    dataUrl,
    mime: file.type || 'application/octet-stream',
    bytes: file.size,
    filename: file.name,
  };
}

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
  // 2026-06-19 · 输入框重构 · 角色想法默认收起(组件内 state · 不上 store)
  // 想法 chip 只在 currentThinking 非空时显 · 默认收起 · 点开往下顶不挤文本
  const [thoughtOpen, setThoughtOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const recording    = useAppStore((s) => s.recording);
  const micMuted     = useAppStore((s) => s.micMuted);
  const status       = useAppStore((s) => s.status);
  const recordingMode = useAppStore((s) => s.recordingMode);
  // 2026-06-05 · "真在听" 高亮:VAD 模式看 vadState · 手动模式看 recording。
  // 双源任一翻 truthy → 按钮点亮。手动话筒图标 + 点亮 = VAD 残留 active(bug)。
  const vadState     = useAppStore((s) => s.vadState);
  const ttsEnabled   = useAppStore((s) => s.ttsEnabled);
  // 2026-06-21 双开关:thinking/search · 状态走 store + setConfigField 持久化
  // · 与 SettingsPanelLegacy 同源 · 共享 lib/toggleConfig:toggleConfigField
  const enableThinking = useAppStore((s) => s.enableThinking);
  const enableSearch   = useAppStore((s) => s.enableSearch);
  const currentThinking = useAppStore((s) => s.currentThinking);
  const currentToolName = useAppStore((s) => s.currentToolName);

  // 2026-06-19 · 图片输入 MVP · store 队列 + 2 setter
  // clearAttachments 由 useWebSocket.sendText 内部调 · ChatInput 不直接用
  const pendingAttachments = useAppStore((s) => s.pendingAttachments);
  const addAttachment = useAppStore((s) => s.addAttachment);
  const removeAttachment = useAppStore((s) => s.removeAttachment);

  // 2026-06-19 · 删手动打断按钮 · sendInterrupt 移出本组件 destructure
  // (useAudio barge-in 仍在用 · 不动那条;ChatInput 不再持手动打断 UI)
  const { sendText, startManual, stopManualAndSend, toggleVad } = useAppApi();

  /** 2026-06-19 · 接 N 个 File · 按 mime 分派(image→压图 / 其它→读 base64)·
   *  失败 toast 单条提示。命中 IMG_MAX_COUNT 总数(image+file)或总和上限拒。
   *  补丁 A · 总和上限 TOTAL_MAX_BYTES 防 ws 帧爆 16MB。 */
  const handleFiles = async (files: FileList | File[] | null) => {
    if (!files || files.length === 0) return;
    setImgError(null);
    const arr = Array.from(files);
    const state = useAppStore.getState();
    const currentCount = state.pendingAttachments.length;
    if (currentCount + arr.length > IMG_MAX_COUNT) {
      setImgError(`最多 ${IMG_MAX_COUNT} 个附件 · 当前已 ${currentCount}`);
      return;
    }
    // 累加已在队列里的原字节数(image 用压缩后 bytes / file 用原 bytes)
    let totalBytes = state.pendingAttachments.reduce((s, a) => s + a.bytes, 0);
    for (const f of arr) {
      try {
        const isImage = f.type.startsWith('image/');
        const a = isImage ? await compressImage(f) : await readFileAsDataUrl(f);
        // 补丁 A · 单文件 + 总和双层 cap
        if (a.bytes > FILE_MAX_BYTES) {
          throw new Error(`> ${FILE_MAX_BYTES / 1024 / 1024}MB`);
        }
        if (totalBytes + a.bytes > TOTAL_MAX_BYTES) {
          throw new Error(`附件总和超 ${TOTAL_MAX_BYTES / 1024 / 1024}MB`);
        }
        addAttachment({
          kind: isImage ? 'image' : 'file',
          dataUrl: a.dataUrl,
          mime: a.mime,
          bytes: a.bytes,
          filename: isImage ? undefined : (a as { filename: string }).filename,
        });
        totalBytes += a.bytes;
      } catch (err) {
        const msg = (err as Error).message || '附件处理失败';
        setImgError(`${f.name}:${msg}`);
        console.warn('[ChatInput] attachment add failed', f.name, err);
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

  const onPaste = async (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
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
        ? atts.map((a) => ({
            kind: a.kind,
            dataUrl: a.dataUrl,
            mime: a.mime,
            filename: a.filename,
          }))
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

  // 2026-06-19 · handleInterrupt 已删除 · 手动 ⊘ 按钮取消(barge-in 自动打断
  // 仍在 useAudio.ts 内基于音量阈值触发 · 后端 ws.py:1295 interrupt 帧路径不变)

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // 2026-06-19 · textarea Enter 发送(preventDefault)/ Shift+Enter 换行(走原生)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // 发送 enable 条件:文字非空 或 附件非空(pin 1)
  const canSend = text.trim().length > 0 || pendingAttachments.length > 0;

  // 2026-06-19 · textarea 自增长(方案 B · JS)
  // 每次 text 变化重置 height='auto' 再读 scrollHeight 写回 ·
  // clamp 到 line-height × MAX_LINES + 上下 padding · 超出内部滚动条出来。
  // useLayoutEffect 防 flicker(布局帧内同步算 + 写)。
  useLayoutEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    // computed line-height · text-sm 默认 leading 1.25 (=17.5px on 14px font);
    // 兜底 20px 防 NaN
    const cs = getComputedStyle(ta);
    const lh = parseFloat(cs.lineHeight) || 20;
    const padY = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    const max = lh * TEXTAREA_MAX_LINES + padY;
    ta.style.height = `${Math.min(ta.scrollHeight, max)}px`;
  }, [text]);

  // 角色想法面板:currentThinking 翻 null 时自动收起(下轮重置)
  // sendText 前会 clearCurrentThinking · thoughtOpen 跟实际 thought 状态同步
  useLayoutEffect(() => {
    if (!currentThinking) setThoughtOpen(false);
  }, [currentThinking]);

  // 2026-06-19 · 输入框重构 · 派生 Mic 簇展示参数(原 IIFE 拆出 ·
  // JSX 内只关心 render · 状态计算单独)
  const isVad = recordingMode === 'vad';
  const isListening = isVad
    ? (vadState === 'active' || vadState === 'recording')
    : recording;
  const MicIcon = isVad ? AudioWaveform : Mic;
  const micTitle = isListening
    ? (isVad ? '停止监听' : '停止录音')
    : (isVad ? '开始监听' : '开始录音');

  // 2026-06-19 · Build 1 · 共享 button / chip 样式 · button-size 走 CSS var ·
  // lucide-react `size` prop 是 SVG width/height 属性 · 不解析 CSS 变量 · 必须
  // 给 JS 数值常量 · 跟 themes.css `--input-icon-size: 16px` 同步(Build 2 设置
  // 项要可调 icon 尺寸时,这里改成 useState/CSS computed 读)
  const ICON_SIZE = 16;             // 同步 themes.css --input-icon-size
  const CHIP_ICON_SIZE = 12;        // 同步 themes.css --input-chip-icon-size
  const btnSize: React.CSSProperties = {
    width: 'var(--input-button-size)',
    height: 'var(--input-button-size)',
  };
  const btnBaseClass =
    'rounded-full flex items-center justify-center transition disabled:opacity-30 disabled:cursor-not-allowed';

  return (
    <div
      className="flex flex-col shrink-0"
      onDragOver={onDragOver}
      onDrop={onDrop}
      style={{
        gap: 'var(--input-row-gap)',
        padding: 'var(--input-padding-y) var(--input-padding-x)',
        borderRadius: 'var(--input-radius)',
        background: 'var(--glass-bg)',
        backdropFilter: 'blur(var(--glass-blur))',
        WebkitBackdropFilter: 'blur(var(--glass-blur))',
        border: 'var(--glass-border)',
        boxShadow: 'var(--glass-shadow)',
      }}
    >
      {/* ═══ 区 A · 多行 textarea · 满宽 · 自增长方案 B ═════════════════════
          Enter 发送(preventDefault)· Shift+Enter 换行(原生)·
          useLayoutEffect[text] 内 height='auto' → scrollHeight → clamp 写回 ·
          max 5-6 行后内部滚动 · 尺寸全走 var(--input-*)*/}
      <textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        onPaste={onPaste}
        placeholder="输入消息(可拖图 / 文件 / 粘贴 / 选择)…"
        rows={1}
        className="w-full resize-none rounded-xl outline-none focus:ring-1"
        style={{
          background: 'var(--color-bg-input)',
          color: 'var(--color-text-primary)',
          fontSize: 'var(--input-text-size)',
          lineHeight: 'var(--input-text-leading)',
          padding: '6px 12px',
        }}
      />

      {/* ═══ 附件预览带 · 区 A 与 区 B 之间 · 锁定决策:保留这里 ═══════════════
          按 kind 分支:image → 12×12 缩略图;file → 文件卡片(FileText icon
          + filename truncate + mime 小标 + X 移除)*/}
      {(pendingAttachments.length > 0 || imgError) && (
        <div className="flex flex-wrap items-center gap-2">
          {pendingAttachments.map((a) => (
            a.kind === 'file' ? (
              <div
                key={a.id}
                className="relative flex items-center gap-2 rounded-md overflow-hidden pl-2 pr-6 py-1.5"
                style={{
                  background: 'var(--color-bg-elevated)',
                  border: '1px solid var(--color-border)',
                  maxWidth: 220,
                }}
                title={`${a.filename ?? ''} · ${a.mime || 'unknown'} · ${Math.round(a.bytes / 1024)} KB`}
              >
                <FileText size={16} style={{ color: 'var(--color-text-secondary)' }} />
                <div className="flex flex-col min-w-0">
                  <span
                    className="text-[11px] truncate"
                    style={{ color: 'var(--color-text-primary)', maxWidth: 160 }}
                  >
                    {a.filename ?? 'file'}
                  </span>
                  <span
                    className="text-[9px]"
                    style={{ color: 'var(--color-text-secondary)' }}
                  >
                    {Math.round(a.bytes / 1024)} KB
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => removeAttachment(a.id)}
                  className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full flex items-center justify-center"
                  style={{ background: 'rgba(0, 0, 0, 0.6)', color: '#fff' }}
                  title="移除"
                >
                  <X size={10} />
                </button>
              </div>
            ) : (
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
                  style={{ background: 'rgba(0, 0, 0, 0.6)', color: '#fff' }}
                  title="移除"
                >
                  <X size={10} />
                </button>
              </div>
            )
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

      {/* ═══ 区 B · 单条工具条 · 3 簇 左→右 ═════════════════════════════════
          簇1 输入类:ImagePlus + 可扩展 flex group(留位后加)
          簇2 活动类:微型 StatusBadge(decision ①)+ tool spinner + 想法 chip
                     · 想法 popover 向上弹
                     (2026-06-19 删手动打断按钮 · barge-in 自动打断仍在
                      useAudio.ts 内基于音量阈值触发 · idle 时簇2 自动全干净)
          簇3 语音/发送:Mic / TTS(mute)/ Send(ArrowUp)*/}
      <div className="flex items-center justify-between gap-2">
        {/* ── 簇1 · 输入类 · 可扩展 flex group(现放 ImagePlus · 留位后加)── */}
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPT_ALL}
            multiple
            onChange={onFileChange}
            style={{ display: 'none' }}
          />
          <button
            className={btnBaseClass}
            style={{
              ...btnSize,
              background: 'color-mix(in srgb, var(--color-bg-elevated) 80%, transparent)',
              color: pendingAttachments.length > 0
                ? 'var(--color-text-accent)'
                : 'var(--color-text-secondary)',
            }}
            onClick={onPickImages}
            disabled={pendingAttachments.length >= IMG_MAX_COUNT}
            title={
              pendingAttachments.length >= IMG_MAX_COUNT
                ? `已达上限 ${IMG_MAX_COUNT} 个`
                : '加图片 / 文件(拖拽 / 粘贴 / 选择)'
            }
            aria-label="加附件"
          >
            <Paperclip size={ICON_SIZE} />
          </button>
          {/* 未来后加按钮:同 group 续写 · 别硬塞单按钮 */}
        </div>

        {/* ── 簇2 · 活动类 · 全部运行时状态(决策 ① 微型 status + tool +
              想法 chip)· 想法 popover 向上弹 · 空闲时全条件渲染 = 干净空 ── */}
        <div className="flex items-center gap-2 min-w-0">
          {/* 决策 ① · 微型 AI 状态指示 · idle 时整个 null · 非 idle 才显小色
              点 + 极短标签 · 不重复左栏 ConnectionDot(那是 WS 连接,不是 AiStatus)*/}
          <StatusMicro status={status} />

          {/* UX-004 · tool loading indicator · 字号走 chip-text-size */}
          {currentToolName && (
            <div
              className="flex items-center gap-1 rounded-full animate-pulse max-w-[200px] overflow-hidden text-ellipsis whitespace-nowrap"
              style={{
                background: 'color-mix(in srgb, var(--color-bg-elevated) 60%, transparent)',
                color: 'var(--color-text-secondary)',
                border: '1px dashed var(--color-border-subtle)',
                fontSize: 'var(--input-chip-text-size)',
                padding: 'var(--input-chip-pad-y) var(--input-chip-pad-x)',
              }}
              title={`tool: ${currentToolName}`}
            >
              <Loader2
                size={CHIP_ICON_SIZE}
                className="shrink-0 animate-spin"
              />
              <span className="truncate">{toolLoadingLabel(currentToolName)}</span>
            </div>
          )}

          {/* v3-F · AI 内心独白 chip · 默认收起 · 点开【向上】popover
              不挤文本横向 · currentThinking 空时整 chip 隐藏 */}
          {currentThinking && (
            <div className="relative">
              <button
                type="button"
                onClick={() => setThoughtOpen((v) => !v)}
                className="flex items-center gap-1 rounded-full italic transition"
                style={{
                  background: 'color-mix(in srgb, var(--color-accent) 18%, transparent)',
                  color: 'var(--color-text-accent)',
                  border: '1px solid color-mix(in srgb, var(--color-accent) 30%, transparent)',
                  fontSize: 'var(--input-chip-text-size)',
                  padding: 'var(--input-chip-pad-y) var(--input-chip-pad-x)',
                }}
                title={thoughtOpen ? '收起角色想法' : '展开角色想法'}
                aria-expanded={thoughtOpen}
              >
                <Sparkles size={12} className="shrink-0" />
                <span>角色想法</span>
                {thoughtOpen
                  ? <ChevronUp size={12} className="shrink-0" />
                  : <ChevronDown size={12} className="shrink-0" />}
              </button>
              {/* 想法 popover · 从 chip 上方 8px 向上弹 · 右对齐 chip 防溢出窗口
                  · max 360 宽 + max 200 高 + 内部 scroll · 不顶到 textarea */}
              {thoughtOpen && (
                <div
                  className="absolute italic rounded-lg leading-relaxed whitespace-pre-wrap break-words shadow-lg"
                  style={{
                    bottom: 'calc(100% + 8px)',
                    right: 0,
                    width: 'min(360px, calc(100vw - 32px))',
                    maxHeight: '200px',
                    overflowY: 'auto',
                    padding: '8px 12px',
                    fontSize: 'var(--input-chip-text-size)',
                    background: 'var(--color-bg-surface)',
                    color: 'var(--color-text-accent)',
                    border: '1px solid color-mix(in srgb, var(--color-accent) 30%, transparent)',
                    zIndex: 10,
                  }}
                >
                  {currentThinking}
                </div>
              )}
            </div>
          )}

          {/* 2026-06-19 · 手动 Ban 打断按钮已删 · barge-in 自动打断仍在
              useAudio.ts:455 区段(用户开口超 INTERRUPT_THRESHOLD 触发)·
              ws.py:1295 interrupt 帧路径不变 · StatusMicro 'interrupted'
              态自动打断时仍会显示 */}
        </div>

        {/* ── 簇3 · 语音 / 发送 · Thinking / Search / Mic / TTS(mute)/ Send ── */}
        <div className="flex items-center gap-2">
          {/* 2026-06-21 v2 · 双开关 pill 重设计 ·
              原圆钮(仅 icon + 35% mix 背景)状态太隐蔽 → 改 rounded-full
              pill(icon + 文字),开 = 实心 accent 不透明,关 = 幽灵(透明 +
              1px border),点一下填充翻转 = 强反馈。逻辑不变(toggleConfigField
              同源)· 文字 "思考"/"联网" 短,全称走 tooltip。 */}
          {/* 深度思考 toggle · On → qwen3.x 走思考链 · Off → 立即出 content
              · 非 thinking 模型后端 silent skip 但 UI 仍可点(同 enableSearch) */}
          <button
            className={
              'rounded-full inline-flex items-center justify-center gap-1.5 ' +
              'text-xs font-medium transition-all duration-150 disabled:opacity-30'
            }
            style={
              enableThinking
                ? {
                    height: 'var(--input-button-size)',
                    paddingLeft: 10,
                    paddingRight: 12,
                    background: 'var(--color-accent)',
                    color: 'var(--color-bubble-user-text)',
                  }
                : {
                    height: 'var(--input-button-size)',
                    paddingLeft: 10,
                    paddingRight: 12,
                    background: 'transparent',
                    color: 'var(--color-text-secondary)',
                    border: '1px solid var(--color-border)',
                  }
            }
            onClick={() => {
              const next = !enableThinking;
              toggleConfigField(
                useAppStore.getState().setEnableThinking,
                'thinking.enable_thinking',
                next,
                (e) => console.error('[ChatInput] thinking toggle failed:', e),
              );
            }}
            title={enableThinking ? '深度思考已开(慢但更细)' : '深度思考已关(回复快)'}
            aria-label={enableThinking ? '关闭深度思考' : '开启深度思考'}
            aria-pressed={enableThinking}
          >
            <Brain size={14} />
            <span>思考</span>
          </button>

          {/* 联网搜索 toggle · On → qwen enable_search native · 非 qwen 后端
              silent skip + warn log */}
          <button
            className={
              'rounded-full inline-flex items-center justify-center gap-1.5 ' +
              'text-xs font-medium transition-all duration-150 disabled:opacity-30'
            }
            style={
              enableSearch
                ? {
                    height: 'var(--input-button-size)',
                    paddingLeft: 10,
                    paddingRight: 12,
                    background: 'var(--color-accent)',
                    color: 'var(--color-bubble-user-text)',
                  }
                : {
                    height: 'var(--input-button-size)',
                    paddingLeft: 10,
                    paddingRight: 12,
                    background: 'transparent',
                    color: 'var(--color-text-secondary)',
                    border: '1px solid var(--color-border)',
                  }
            }
            onClick={() => {
              const next = !enableSearch;
              toggleConfigField(
                useAppStore.getState().setEnableSearch,
                'search.enable_search',
                next,
                (e) => console.error('[ChatInput] search toggle failed:', e),
              );
            }}
            title={enableSearch ? '联网搜索已开' : '联网搜索已关'}
            aria-label={enableSearch ? '关闭联网搜索' : '开启联网搜索'}
            aria-pressed={enableSearch}
          >
            <Globe size={14} />
            <span>联网</span>
          </button>

          {/* Mic · 图标按 recordingMode 切 · 点亮 = 真在听 */}
          <button
            className={btnBaseClass + ' disabled:opacity-40'}
            style={
              isListening
                ? {
                    ...btnSize,
                    background: 'var(--color-accent)',
                    color: 'var(--color-bubble-user-text)',
                  }
                : {
                    ...btnSize,
                    background: 'color-mix(in srgb, var(--color-bg-elevated) 80%, transparent)',
                    color: 'var(--color-text-primary)',
                  }
            }
            onClick={handleMic}
            disabled={micMuted}
            title={micTitle}
            aria-label={micTitle}
            aria-pressed={isListening}
          >
            <MicIcon size={ICON_SIZE} />
          </button>

          {/* TTS toggle(mute) */}
          <button
            className={btnBaseClass}
            style={
              ttsEnabled
                ? {
                    ...btnSize,
                    background: 'color-mix(in srgb, var(--color-accent) 35%, transparent)',
                    color: 'var(--color-text-accent)',
                  }
                : {
                    ...btnSize,
                    background: 'color-mix(in srgb, var(--color-bg-elevated) 80%, transparent)',
                    color: 'var(--color-text-secondary)',
                  }
            }
            onClick={handleTts}
            title={ttsEnabled ? 'TTS 已开启' : 'TTS 已关闭'}
            aria-label={ttsEnabled ? 'TTS 已开启' : 'TTS 已关闭'}
          >
            {ttsEnabled
              ? <Volume2 size={ICON_SIZE} />
              : <VolumeX size={ICON_SIZE} />}
          </button>

          {/* Send · arrow-up 圆钮 · pin 1:image-only 允许 · canSend = text 或 attachments */}
          <button
            className={btnBaseClass}
            style={{
              ...btnSize,
              background: canSend ? 'var(--color-accent)' : 'var(--color-bg-elevated)',
              color: canSend ? 'var(--color-bubble-user-text)' : 'var(--color-text-primary)',
            }}
            onClick={handleSend}
            disabled={!canSend}
            title="发送"
            aria-label="发送"
          >
            <ArrowUp size={ICON_SIZE} />
          </button>
        </div>
      </div>
    </div>
  );
}
