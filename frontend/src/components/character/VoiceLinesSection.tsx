/**
 * v4.0 voice greeting · CharacterPanel "语音问候" section。
 *
 * per PM dispatch(2026-05-22)· 角色管理新 tab 形态:
 *   - 文件上传(accept=".wav,.mp3,.ogg")+ 可选 text_description / language
 *   - 列表:text_description(或 filename)+ duration + ▶ preview + 🗑 delete
 *
 * 类比 PersonasSection / BaseInstructionSection 同款 pattern;CharacterPanel
 * 在 form.mode === 'edit' + form.id !== null 时 render(per 现 PersonasSection
 * 入口条件)。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  deleteVoiceLine,
  listVoiceLines,
  uploadVoiceLine,
  type VoiceLine,
} from '../../lib/voice_lines';

interface VoiceLinesSectionProps {
  characterId: number;
  showToast?: (text: string) => void;
}

function _formatDuration(ms: number | null): string {
  if (ms == null) return '?';
  if (ms < 1000) return `${ms}ms`;
  const sec = ms / 1000;
  if (sec < 60) return `${sec.toFixed(2)}s`;
  return `${Math.floor(sec / 60)}m${(sec % 60).toFixed(0)}s`;
}

const BACKEND_BASE = 'http://127.0.0.1:8000';

export default function VoiceLinesSection({
  characterId,
  showToast,
}: VoiceLinesSectionProps) {
  const [items, setItems] = useState<VoiceLine[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [textDesc, setTextDesc] = useState('');
  const [language, setLanguage] = useState('ja');
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listVoiceLines(characterId);
      setItems(data.items);
    } catch (err) {
      console.warn('[VoiceLinesSection] list failed:', err);
      showToast?.('加载语音列表失败');
    } finally {
      setLoading(false);
    }
  }, [characterId, showToast]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // cleanup preview audio on unmount
  useEffect(() => () => {
    try { previewAudioRef.current?.pause(); } catch { /* ignore */ }
  }, []);

  const handleUpload = useCallback(async () => {
    const file = fileInputRef.current?.files?.[0];
    if (!file) {
      showToast?.('请先选文件');
      return;
    }
    setUploading(true);
    try {
      await uploadVoiceLine(characterId, file, {
        text_description: textDesc.trim() || undefined,
        language: language.trim() || undefined,
      });
      showToast?.('上传成功');
      // reset inputs
      if (fileInputRef.current) fileInputRef.current.value = '';
      setTextDesc('');
      await refresh();
    } catch (err) {
      console.warn('[VoiceLinesSection] upload failed:', err);
      showToast?.(`上传失败:${err instanceof Error ? err.message : 'unknown'}`);
    } finally {
      setUploading(false);
    }
  }, [characterId, textDesc, language, refresh, showToast]);

  const handlePreview = useCallback((item: VoiceLine) => {
    // 停掉之前的预览
    try { previewAudioRef.current?.pause(); } catch { /* ignore */ }
    const url = `${BACKEND_BASE}${item.audio_url}`;
    const audio = new Audio(url);
    previewAudioRef.current = audio;
    audio.play().catch((err) => {
      console.warn('[VoiceLinesSection] preview play failed:', err);
      showToast?.('播放失败');
    });
  }, [showToast]);

  const handleDelete = useCallback(async (item: VoiceLine) => {
    if (!confirm(`确认删除 #${item.id}?`)) return;
    try {
      await deleteVoiceLine(characterId, item.id);
      showToast?.('已删除');
      await refresh();
    } catch (err) {
      console.warn('[VoiceLinesSection] delete failed:', err);
      showToast?.(`删除失败:${err instanceof Error ? err.message : 'unknown'}`);
    }
  }, [characterId, refresh, showToast]);

  return (
    <section
      className="space-y-2 mb-4 rounded-md p-3"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-elevated) 60%, transparent)',
        border: '1px solid var(--color-border)',
      }}
    >
      <h4
        className="text-sm font-medium mb-2"
        style={{ color: 'var(--color-text-primary)' }}
      >
        🎙 语音问候(立绘馆 onEnter 随机播)
      </h4>
      <p
        className="text-[10px] mb-2"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        上传 .wav / .mp3 / .ogg(≤ 5MB)· 在立绘馆点选此角色时随机播放一条
      </p>

      {/* 上传区 */}
      <div className="space-y-2 pb-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <input
          ref={fileInputRef}
          type="file"
          accept=".wav,.mp3,.ogg,audio/wav,audio/mpeg,audio/ogg"
          className="block w-full text-xs"
          style={{ color: 'var(--color-text-primary)' }}
        />
        <input
          type="text"
          value={textDesc}
          onChange={(e) => setTextDesc(e.target.value)}
          placeholder="文本描述(可选,如 「あら、来たのね。」)"
          className="w-full rounded-md px-2 py-1.5 text-xs focus:outline-none"
          style={{
            background: 'var(--color-bg-input)',
            color: 'var(--color-text-primary)',
            border: '1px solid var(--color-border)',
          }}
        />
        <div className="flex gap-2 items-center">
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className="rounded-md px-2 py-1.5 text-xs focus:outline-none"
            style={{
              background: 'var(--color-bg-input)',
              color: 'var(--color-text-primary)',
              border: '1px solid var(--color-border)',
            }}
          >
            <option value="ja">ja</option>
            <option value="zh">zh</option>
            <option value="en">en</option>
            <option value="">(unspecified)</option>
          </select>
          <button
            type="button"
            disabled={uploading}
            onClick={handleUpload}
            className="rounded-md px-3 py-1.5 text-xs font-medium transition disabled:opacity-50"
            style={{
              background: 'var(--color-accent)',
              color: 'var(--color-bg-elevated)',
            }}
          >
            {uploading ? '上传中…' : '上传'}
          </button>
        </div>
      </div>

      {/* 列表 */}
      <div className="space-y-1 mt-2">
        {loading && (
          <p className="text-[11px]" style={{ color: 'var(--color-text-secondary)' }}>
            加载中…
          </p>
        )}
        {!loading && items.length === 0 && (
          <p className="text-[11px]" style={{ color: 'var(--color-text-secondary)' }}>
            还没有语音(立绘馆点此角色时静默不播)
          </p>
        )}
        {items.map((item) => (
          <div
            key={item.id}
            className="flex items-center gap-2 rounded px-2 py-1.5 text-xs"
            style={{ background: 'color-mix(in srgb, var(--color-bg) 50%, transparent)' }}
          >
            <span className="flex-1 truncate" style={{ color: 'var(--color-text-primary)' }}>
              {item.text_description || (
                <span style={{ color: 'var(--color-text-secondary)' }}>
                  (无描述)
                </span>
              )}
            </span>
            <span
              className="shrink-0 text-[10px]"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {_formatDuration(item.duration_ms)}
              {item.language ? ` · ${item.language}` : ''}
            </span>
            <button
              type="button"
              onClick={() => handlePreview(item)}
              title="试听"
              className="shrink-0 text-base hover:opacity-70 transition"
            >
              ▶
            </button>
            <button
              type="button"
              onClick={() => handleDelete(item)}
              title="删除"
              className="shrink-0 text-base hover:opacity-70 transition"
            >
              🗑
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
