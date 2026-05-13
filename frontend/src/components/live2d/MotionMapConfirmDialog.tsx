/**
 * Stage 2.2.1 — Live2D 上传成功后,询问是否把默认 motion_map 写入当前
 * character.motion_map_json 的确认对话框。
 *
 * 设计:
 *   - 显示前 3 个 motion entry preview(完整 list 可能 ~10 项,折叠避免占屏)
 *   - "应用" → 调用方走 patchCharacter
 *   - "跳过" → 不动 DB,关 modal;用户后续可手动配 motion_map_json
 *   - 仅在 character.mode === 'edit' 且 character.id 存在时弹出;create 模式
 *     由 parent 在保存角色后再决策(本组件不处理 create case)
 */
import { useMemo } from 'react';
import { Wand2 } from 'lucide-react';
import type { Live2DMotionEntry, Live2DUploadResult } from '../../lib/live2d';

interface MotionMapConfirmDialogProps {
  characterName: string;
  slug: string;
  motionMap: Record<string, Live2DMotionEntry>;
  onApply: () => void;
  onSkip: () => void;
  applying: boolean;
}

const PREVIEW_COUNT = 3;

export default function MotionMapConfirmDialog({
  characterName,
  slug,
  motionMap,
  onApply,
  onSkip,
  applying,
}: MotionMapConfirmDialogProps) {
  const entries = useMemo(
    () => Object.entries(motionMap),
    [motionMap],
  );
  const previewEntries = entries.slice(0, PREVIEW_COUNT);
  const extraCount = Math.max(0, entries.length - PREVIEW_COUNT);

  const fullJson = useMemo(
    () => JSON.stringify(motionMap, null, 2),
    [motionMap],
  );

  return (
    <div
      className="fixed inset-0 z-[56] flex items-center justify-center"
      style={{
        background:
          'color-mix(in srgb, var(--color-bg-base) 60%, transparent)',
      }}
      onClick={applying ? undefined : onSkip}
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
          className="text-sm font-semibold mb-2 flex items-center gap-2"
          style={{ color: 'var(--color-text-primary)' }}
        >
          <Wand2 size={14} style={{ color: 'var(--color-accent)' }} />
          应用默认 motion map?
        </h4>
        <p
          className="text-xs mb-3"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          从 <span className="font-mono">{slug}</span> 的 .motion3.json
          文件名生成了 <b>{entries.length}</b> 条默认 motion 映射。是否写入
          <b> {characterName}</b> 的 motion_map_json?
        </p>

        {entries.length > 0 ? (
          <div
            className="rounded-md text-[11px] font-mono p-2 mb-3"
            style={{
              background: 'var(--color-bg-input)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
          >
            <pre className="whitespace-pre-wrap break-all">
{`{
${previewEntries.map(
  ([k, v]) => `  "${k}": { "group": "${v.group}", "index": ${v.index} }`,
).join(',\n')}${extraCount > 0 ? `\n  ... 还有 ${extraCount} 条` : ''}
}`}
            </pre>
          </div>
        ) : (
          <div
            className="text-[11px] mb-3"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            该模型 zip 内未发现 ``.motion3.json`` 文件;motion map 默认为空。
          </div>
        )}

        <details
          className="text-[10px] mb-3"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          <summary className="cursor-pointer">查看完整 JSON</summary>
          <pre
            className="mt-1 rounded p-2 whitespace-pre-wrap break-all"
            style={{
              background: 'var(--color-bg-input)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
          >
            {fullJson}
          </pre>
        </details>

        <p
          className="text-[10px] mb-3"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          "跳过" 不影响模型可用性;motion 标签触发的动作会走前端硬编码兜底
          (frontend/src/config/live2d.ts motionMap)。之后可在角色 motion_map_json
          字段手动编辑。
        </p>

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onSkip}
            disabled={applying}
            className="px-3 py-1.5 text-xs rounded-md transition disabled:opacity-50"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-primary)',
            }}
          >
            跳过
          </button>
          <button
            type="button"
            onClick={onApply}
            disabled={applying || entries.length === 0}
            className="px-3 py-1.5 text-xs rounded-md transition disabled:opacity-50"
            style={{
              background: 'var(--color-accent)',
              color: 'var(--color-bubble-user-text)',
            }}
          >
            {applying ? '应用中…' : '应用 motion map'}
          </button>
        </div>
      </div>
    </div>
  );
}
