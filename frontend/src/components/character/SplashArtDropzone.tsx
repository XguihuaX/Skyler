/**
 * v4-fan chunk 5 — Splash art 上传 dropzone(inline,跟 Live2DDropzone 不同
 * 不走 modal)。
 *
 * 设计:
 *   - **inline**:嵌在 CharacterPanel 编辑表单内,跟 avatar / background
 *     section 同级。Live2DDropzone 是 modal 因为 zip 上传是大动作 + 后续
 *     有 motion_map 弹窗;splash art 单文件 + 立刻完成,inline 更顺。
 *   - **HTML5 native drag/drop + click-to-pick**:抄 Live2DDropzone 的同
 *     pattern,~30 行 boilerplate。不引 react-dropzone (依赖红线)。
 *   - **Tauri MIME 兜底**:browser 偶尔填空 MIME,backend
 *     ``_resolve_splash_ext`` 已兜底从 filename 扩展名判;client 端也用同
 *     pattern (双层防御)。
 *   - **client size limit**:5 MB,跟 backend ``_MAX_SPLASH_SIZE`` 对齐。
 *     先 client 拦,避免大文件白等上传 + 服务器 413。
 *
 * 两态视觉:
 *   - 有 currentUrl:96×144 缩略图 (2:3) + ``替换`` + ``删除`` 按钮
 *   - 无 currentUrl:80px 高 dashed dropzone + 上传文字
 *
 * 删除走 onDeleteRequest 回调让 parent 弹自己的 ConfirmModal (CharacterPanel
 * 已有该组件,不重复造)。
 */
import { useCallback, useRef, useState } from 'react';
import { AlertTriangle, Loader2, Trash2, Upload } from 'lucide-react';
import { uploadSplashArt } from '../../lib/characters';

const MAX_BYTES = 5 * 1024 * 1024;            // 与 backend _MAX_SPLASH_SIZE 对齐
const ACCEPT_EXTS = ['.png', '.jpg', '.jpeg', '.webp'] as const;
const ACCEPT_MIMES = new Set([
  'image/png', 'image/jpeg', 'image/webp',
]);

interface SplashArtDropzoneProps {
  characterId: number;
  /** 当前 splash_art_url(从 character 行读)。null/空 → 显示 dropzone。 */
  currentUrl?: string | null;
  /** 上传成功 → parent toast + refresh characters。 */
  onUploadSuccess: (newUrl: string) => void;
  /** 用户点 "删除" → parent 决定弹 confirm 对话框 + 调 deleteSplashArt。 */
  onDeleteRequest: () => void;
}

function isAcceptableImage(file: File): { ok: true } | { ok: false; reason: string } {
  // MIME 优先
  const mime = (file.type || '').toLowerCase();
  if (mime && ACCEPT_MIMES.has(mime)) return { ok: true };

  // 扩展名兜底(Tauri WebView 偶尔 type=''),提取后小写比对
  const lower = file.name.toLowerCase();
  const ext = ACCEPT_EXTS.find((e) => lower.endsWith(e));
  if (ext) return { ok: true };

  return {
    ok: false,
    reason: `需要 png / jpg / webp;收到 ${file.name || '(未命名)'}`
            + (mime ? ` (${mime})` : ''),
  };
}

export default function SplashArtDropzone({
  characterId,
  currentUrl,
  onUploadSuccess,
  onDeleteRequest,
}: SplashArtDropzoneProps) {
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 替换模式:有 currentUrl 时,默认显示缩略图;点"替换"切到 dropzone
  const [forceDropzone, setForceDropzone] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const showDropzone = !currentUrl || forceDropzone;

  const doUpload = useCallback(
    async (file: File) => {
      setError(null);
      setUploading(true);
      try {
        const result = await uploadSplashArt(characterId, file);
        onUploadSuccess(result.splash_art_url);
        setForceDropzone(false);    // 上传成功 → 缩略图态
      } catch (e) {
        const err = e as Error & { status?: number };
        const detail = err.message || '上传失败';
        setError(err.status ? `${err.status} · ${detail}` : detail);
      } finally {
        setUploading(false);
      }
    },
    [characterId, onUploadSuccess],
  );

  const handleFile = useCallback(
    (file: File) => {
      const check = isAcceptableImage(file);
      if (!check.ok) {
        setError(check.reason);
        return;
      }
      if (file.size > MAX_BYTES) {
        setError(
          `文件过大:${(file.size / 1024 / 1024).toFixed(1)} MB > 5 MB 上限`,
        );
        return;
      }
      void doUpload(file);
    },
    [doUpload],
  );

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    if (!uploading) setDragOver(true);
  };
  const onDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (uploading) return;
    const file = e.dataTransfer?.files?.[0];
    if (file) handleFile(file);
  };
  const onPick = () => {
    if (uploading) return;
    fileInputRef.current?.click();
  };
  const onFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    e.target.value = '';
  };

  return (
    <div>
      {/* 缩略图态:有 currentUrl 且未点替换 */}
      {!showDropzone && currentUrl && (
        <div className="flex items-start gap-3">
          <div
            className="rounded-md overflow-hidden flex-shrink-0"
            style={{
              width: 96,
              height: 144,
              border: '1px solid var(--color-border)',
              background: 'var(--color-bg-elevated)',
            }}
          >
            <img
              src={currentUrl}
              alt="splash art"
              draggable={false}
              loading="lazy"
              decoding="async"
              className="w-full h-full"
              style={{ objectFit: 'cover', objectPosition: 'center top' }}
              onError={(e) => {
                // 文件被手动删 → 回到 dropzone 让用户重传
                (e.currentTarget as HTMLImageElement).style.opacity = '0.2';
              }}
            />
          </div>
          <div className="flex-1 flex flex-col gap-2">
            <button
              type="button"
              onClick={() => {
                setError(null);
                setForceDropzone(true);
              }}
              className="px-3 py-1.5 text-xs rounded-md transition flex items-center justify-center gap-1.5"
              style={{
                background: 'var(--color-bg-elevated)',
                color: 'var(--color-text-primary)',
                border: '1px solid var(--color-border)',
              }}
            >
              <Upload size={12} />
              替换立绘
            </button>
            <button
              type="button"
              onClick={onDeleteRequest}
              className="px-3 py-1.5 text-xs rounded-md transition flex items-center justify-center gap-1.5 text-rose-300 hover:bg-rose-700/30"
              style={{
                background: 'var(--color-bg-elevated)',
                border: '1px solid var(--color-border)',
              }}
            >
              <Trash2 size={12} />
              删除
            </button>
          </div>
        </div>
      )}

      {/* dropzone 态:无 currentUrl 或用户点了替换 */}
      {showDropzone && (
        <div>
          <div
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
            onClick={onPick}
            className="rounded-md flex flex-col items-center justify-center cursor-pointer transition-colors"
            style={{
              border: `2px dashed ${
                dragOver
                  ? 'var(--color-accent)'
                  : 'var(--color-border)'
              }`,
              background: dragOver
                ? 'color-mix(in srgb, var(--color-accent) 8%, transparent)'
                : 'var(--color-bg-input)',
              padding: '20px 16px',
              minHeight: 96,
              opacity: uploading ? 0.6 : 1,
              pointerEvents: uploading ? 'none' : 'auto',
            }}
          >
            {uploading ? (
              <>
                <Loader2
                  size={20}
                  className="animate-spin mb-1.5"
                  style={{ color: 'var(--color-accent)' }}
                />
                <div
                  className="text-xs"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  上传中…
                </div>
              </>
            ) : (
              <>
                <Upload
                  size={20}
                  className="mb-1.5"
                  style={{ color: 'var(--color-text-secondary)' }}
                />
                <div
                  className="text-xs"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  {dragOver ? '释放上传' : '拖入立绘 (.png / .jpg / .webp)'}
                </div>
                <div
                  className="text-[10px] mt-0.5 underline"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  或点击选文件
                </div>
              </>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={onFileInputChange}
          />

          {/* 替换模式下加 "取消" 按钮回缩略图态 */}
          {currentUrl && forceDropzone && !uploading && (
            <button
              type="button"
              onClick={() => {
                setError(null);
                setForceDropzone(false);
              }}
              className="mt-1.5 text-[10px] underline"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              取消(保留当前立绘)
            </button>
          )}
        </div>
      )}

      {error && (
        <div
          className="text-[11px] px-2 py-1.5 rounded mt-2 flex items-start gap-1.5"
          style={{
            background: 'rgba(244, 63, 94, 0.10)',
            border: '1px solid rgba(244, 63, 94, 0.30)',
            color: 'rgb(244, 63, 94)',
          }}
        >
          <AlertTriangle size={12} className="flex-shrink-0 mt-[1px]" />
          <span className="break-words">{error}</span>
        </div>
      )}
    </div>
  );
}
