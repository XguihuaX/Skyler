/**
 * Stage 2.2.1 — Live2D .zip 上传 dropzone(modal)。
 *
 * 设计:
 *   - HTML5 ``dragover`` / ``drop`` 原生 API,~20 行可写,不引 react-dropzone
 *     (依赖红线,见 stage-2-starting-context.md §7 Q5)
 *   - Modal 而非 inline:沿用 AddMCPServerForm + CredentialsModal 的 fixed-
 *     overlay 形态,避免 CharacterPanel 列表/表单整体下推
 *   - 上传进度:fetch 不原生支持 upload progress(需 XHR 才能 onprogress);
 *     MVP 阶段只 spinner + "上传中...",真机 Tauri 走 localhost 通常 < 2s
 *     完成,体感够
 *   - slug 冲突重试:409 时显示 slug input + "改名重试" 按钮,保留已上传
 *     File 引用复用(不让用户重选文件)
 *
 * 调用方契约:
 *   - ``onClose`` —— 用户取消 / 上传成功后关闭
 *   - ``onSuccess(result)`` —— 上传 + 后端验证全部通过;result 内含
 *     ``slug`` / ``motion_map`` / ``model_path``,parent 决定后续 UX
 *     (toast / auto-select / 是否应用 motion_map)
 */
import { useCallback, useRef, useState } from 'react';
import { Upload, Loader2, AlertTriangle } from 'lucide-react';
import {
  uploadLive2DModel,
  type Live2DUploadResult,
} from '../../lib/live2d';

interface Live2DDropzoneProps {
  onClose: () => void;
  onSuccess: (result: Live2DUploadResult) => void;
}

export default function Live2DDropzone({
  onClose,
  onSuccess,
}: Live2DDropzoneProps) {
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // slug-conflict retry state:409 后让用户改名重试,保留已选 File 不丢
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [retrySlug, setRetrySlug] = useState('');

  const fileInputRef = useRef<HTMLInputElement>(null);

  const isZip = (f: File) =>
    f.name.toLowerCase().endsWith('.zip')
    // browser 偶尔填空字符串(Tauri WebView 行为),不一票否决 type 检查
    || f.type === 'application/zip'
    || f.type === 'application/x-zip-compressed';

  const doUpload = useCallback(
    async (file: File, slug?: string) => {
      setError(null);
      setUploading(true);
      try {
        const result = await uploadLive2DModel(file, slug);
        onSuccess(result);
        // parent 关 modal;本地 state 不必清(modal 卸载)
      } catch (e) {
        const err = e as Error & { status?: number };
        setError(err.message || '上传失败');
        if (err.status === 409) {
          // 保留 file 引用,显示 slug 改名 UI
          setPendingFile(file);
        } else {
          setPendingFile(null);
        }
      } finally {
        setUploading(false);
      }
    },
    [onSuccess],
  );

  const handleFile = useCallback(
    (file: File) => {
      if (!isZip(file)) {
        setError(`需要 .zip 文件;收到 ${file.name || '(未命名)'}`);
        setPendingFile(null);
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
    // 允许同名文件重选触发 change
    e.target.value = '';
  };

  const onRetry = () => {
    if (!pendingFile) return;
    const slug = retrySlug.trim() || undefined;
    void doUpload(pendingFile, slug);
  };

  return (
    <div
      className="fixed inset-0 z-[55] flex items-center justify-center"
      style={{
        background:
          'color-mix(in srgb, var(--color-bg-base) 60%, transparent)',
      }}
      onClick={onClose}
    >
      <div
        className="rounded-lg p-5 w-[480px] max-h-[85vh] overflow-y-auto shadow-2xl"
        style={{
          background: 'var(--color-bg-surface)',
          border: '1px solid var(--color-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h4
          className="text-sm font-semibold mb-3"
          style={{ color: 'var(--color-text-primary)' }}
        >
          上传 Live2D 模型
        </h4>

        {/* Dropzone target */}
        <div
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          onClick={onPick}
          className="rounded-md flex flex-col items-center justify-center cursor-pointer transition-colors"
          style={{
            // dashed border 在 dragOver 时换 accent 色
            border: `2px dashed ${
              dragOver
                ? 'var(--color-accent)'
                : 'var(--color-border)'
            }`,
            background: dragOver
              ? 'color-mix(in srgb, var(--color-accent) 8%, transparent)'
              : 'var(--color-bg-input)',
            padding: '32px 16px',
            minHeight: 140,
            opacity: uploading ? 0.6 : 1,
            pointerEvents: uploading ? 'none' : 'auto',
          }}
        >
          {uploading ? (
            <>
              <Loader2
                size={28}
                className="animate-spin mb-2"
                style={{ color: 'var(--color-accent)' }}
              />
              <div
                className="text-sm"
                style={{ color: 'var(--color-text-primary)' }}
              >
                上传中…
              </div>
              <div
                className="text-[11px] mt-1"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                正在验证 + 解压(通常 1-3 秒)
              </div>
            </>
          ) : (
            <>
              <Upload
                size={28}
                className="mb-2"
                style={{ color: 'var(--color-text-secondary)' }}
              />
              <div
                className="text-sm"
                style={{ color: 'var(--color-text-primary)' }}
              >
                {dragOver ? '释放上传' : '拖入 .zip 文件'}
              </div>
              <div
                className="text-[11px] mt-1"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                需包含 .moc3 + .model3.json(可选 textures / motions)
              </div>
              <div
                className="text-[11px] mt-1 underline"
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
          accept=".zip,application/zip,application/x-zip-compressed"
          className="hidden"
          onChange={onFileInputChange}
        />

        {error && (
          <div
            className="text-xs px-2 py-1.5 rounded mt-3 flex items-start gap-2"
            style={{
              background: 'rgba(244, 63, 94, 0.10)',
              border: '1px solid rgba(244, 63, 94, 0.30)',
              color: 'rgb(244, 63, 94)',
            }}
          >
            <AlertTriangle
              size={14}
              className="flex-shrink-0 mt-[1px]"
            />
            <span className="break-words">{error}</span>
          </div>
        )}

        {/* slug-conflict retry block */}
        {pendingFile && !uploading && (
          <div
            className="mt-3 rounded-md p-3"
            style={{
              background: 'var(--color-bg-elevated)',
              border: '1px solid var(--color-border)',
            }}
          >
            <p
              className="text-xs mb-2"
              style={{ color: 'var(--color-text-primary)' }}
            >
              指定一个新 slug 重试(英文 / 数字 / ``-`` / ``_``):
            </p>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={retrySlug}
                onChange={(e) => setRetrySlug(e.target.value)}
                placeholder="my-model-v2"
                className="flex-1 rounded-md px-2 py-1.5 text-sm focus:outline-none font-mono"
                style={{
                  background: 'var(--color-bg-input)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text-primary)',
                }}
                autoComplete="off"
              />
              <button
                type="button"
                onClick={onRetry}
                disabled={!retrySlug.trim()}
                className="px-3 py-1.5 text-xs rounded-md transition disabled:opacity-50"
                style={{
                  background: 'var(--color-accent)',
                  color: 'var(--color-bubble-user-text)',
                }}
              >
                改名重试
              </button>
            </div>
          </div>
        )}

        <div className="flex justify-end pt-4">
          <button
            type="button"
            onClick={onClose}
            disabled={uploading}
            className="px-3 py-1.5 text-xs rounded-md transition disabled:opacity-50"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-primary)',
            }}
          >
            {uploading ? '上传中...' : '取消'}
          </button>
        </div>
      </div>
    </div>
  );
}
