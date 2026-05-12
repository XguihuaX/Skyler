/**
 * v3.5 chunk 11 — SettingsPanel [用户档案] section（取代 chunk 9 [用户画像]）。
 *
 * 结构化 ``users.profile_data`` JSON 字段级展示 + inline edit + 增删 list 项。
 * 后端 endpoints 见 ``backend/routes/users_api.py`` chunk 11 段。
 *
 * UI 风格对齐 chunk 5 ExtensionsSection / chunk 7 sections（顶部 Section
 * 标题 + rounded panel）。
 *
 * profile_data 为 NULL 时显示"尚未生成档案" + [立刻生成] 按钮（mode=
 * incremental，少量对话也能预览）。
 */
import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Trash2, Plus, Pencil, Check, X } from 'lucide-react';
import {
  fetchProfileData,
  patchProfileData,
  deleteProfileData,
  regenerateProfileData,
  type ProfileData,
  type ProfileDataRegenerateMode,
} from '../lib/profileData';

interface Props {
  userId: string;
  showToast: (text: string) => void;
}

const STRING_FIELDS: { key: keyof ProfileData; label: string }[] = [
  { key: 'profession',           label: '职业' },
  { key: 'communication_style',  label: '沟通风格' },
  { key: 'language_preferences', label: '语言偏好' },
  { key: 'active_hours',         label: '活跃时段' },
];
const LIST_FIELDS: { key: keyof ProfileData; label: string }[] = [
  { key: 'current_projects',  label: '当前项目' },
  { key: 'interests',         label: '长期兴趣' },
  { key: 'recurring_topics',  label: '反复出现的话题' },
];


export default function UserProfileSection({ userId, showToast }: Props) {
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [regenMode, setRegenMode] = useState<ProfileDataRegenerateMode | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetchProfileData(userId);
      setProfile(r.profile_data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const onPatchString = async (key: keyof ProfileData, value: string | null) => {
    try {
      const r = await patchProfileData(userId, { [key]: value } as Partial<ProfileData>);
      setProfile(r.profile_data);
    } catch (e) {
      showToast(`保存失败：${(e as Error).message}`);
    }
  };

  const onPatchList = async (key: keyof ProfileData, value: string[]) => {
    try {
      const r = await patchProfileData(userId, { [key]: value } as Partial<ProfileData>);
      setProfile(r.profile_data);
    } catch (e) {
      showToast(`保存失败：${(e as Error).message}`);
    }
  };

  const onRegen = async (mode: ProfileDataRegenerateMode) => {
    setRegenMode(mode);
    try {
      const r = await regenerateProfileData(userId, mode);
      if (r.status === 'regenerated') {
        showToast(mode === 'reset' ? '档案已完全重置' : '档案已增量更新');
      } else {
        showToast(r.detail || `跳过：${r.status}`);
      }
      await refresh();
    } catch (e) {
      showToast(`重生失败：${(e as Error).message}`);
    } finally {
      setRegenMode(null);
    }
  };

  return (
    <>
      <section className="mb-4">
        <h3
          className="text-sm font-semibold mb-2"
          style={{ color: 'var(--color-text-primary)' }}
        >
          用户档案
        </h3>
        <div
          className="rounded-md px-3 py-2 space-y-2"
          style={{
            background: 'var(--color-bg-surface)',
            border: '1px solid var(--color-border)',
          }}
        >
          <p
            className="text-[11px]"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            Momo 根据你过去 7 天说过的话整理（每天 23:55 自动更新；只填客观事实）
          </p>

          {loading && !profile && (
            <div className="text-xs py-2" style={{ color: 'var(--color-text-secondary)' }}>
              加载中…
            </div>
          )}
          {error && <div className="text-xs py-2 text-rose-300">加载失败：{error}</div>}

          {profile === null && !loading && !error && (
            <div
              className="text-xs rounded p-2"
              style={{
                background: 'var(--color-bg-elevated)',
                color: 'var(--color-text-secondary)',
                border: '1px solid var(--color-border-subtle)',
              }}
            >
              尚未生成档案（cron 每天 23:55 自动跑；可点[立刻生成]立即预览）
            </div>
          )}

          {profile && (
            <div className="space-y-1.5">
              {STRING_FIELDS.map(({ key, label }) => (
                <StringField
                  key={key}
                  label={label}
                  value={(profile[key] as string | null) ?? null}
                  onSave={(v) => void onPatchString(key, v)}
                />
              ))}
              {LIST_FIELDS.map(({ key, label }) => (
                <ListField
                  key={key}
                  label={label}
                  values={(profile[key] as string[]) ?? []}
                  onSave={(v) => void onPatchList(key, v)}
                />
              ))}
            </div>
          )}

          <div
            className="text-[10px] flex justify-end"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <button
              type="button"
              onClick={() => void refresh()}
              disabled={loading}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded hover:opacity-80 disabled:opacity-50"
              style={{ color: 'var(--color-text-secondary)' }}
              title="重新拉取当前档案"
            >
              <RefreshCw size={10} className={loading ? 'animate-spin' : ''} />
              刷新
            </button>
          </div>

          <div className="flex gap-2 pt-1">
            <button
              type="button"
              onClick={() => void onRegen('incremental')}
              disabled={loading || regenMode !== null}
              className="text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded hover:opacity-80 disabled:opacity-50"
              style={{
                background: 'var(--color-bg-elevated)',
                color: 'var(--color-text-primary)',
                border: '1px solid var(--color-border)',
              }}
              title="保留旧字段 + 合并近期数据"
            >
              <RefreshCw
                size={11}
                className={regenMode === 'incremental' ? 'animate-spin' : ''}
              />
              {regenMode === 'incremental'
                ? '生成中…'
                : profile === null
                  ? '立刻生成'
                  : '增量更新'}
            </button>
            {profile !== null && (
              <button
                type="button"
                onClick={() => setConfirmReset(true)}
                disabled={loading || regenMode !== null}
                className="text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded hover:opacity-80 disabled:opacity-50"
                style={{
                  background: 'var(--color-bg-elevated)',
                  color: 'var(--color-text-primary)',
                  border: '1px solid var(--color-border)',
                }}
                title="丢弃旧档案，从最近 7 天 user 消息完全重写"
              >
                <Trash2 size={11} />
                {regenMode === 'reset' ? '生成中…' : '完全重置'}
              </button>
            )}
          </div>
        </div>
      </section>

      {confirmReset && (
        <ConfirmModal
          text={'完全重置当前档案？\n\n旧档案将丢弃，从过去 7 天用户消息重新生成。'}
          onCancel={() => setConfirmReset(false)}
          onConfirm={() => {
            setConfirmReset(false);
            void onRegen('reset');
          }}
        />
      )}
    </>
  );
}


// ---------------------------------------------------------------------------
// String field (inline edit)
// ---------------------------------------------------------------------------


function StringField({
  label,
  value,
  onSave,
}: {
  label: string;
  value: string | null;
  onSave: (v: string | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? '');

  useEffect(() => {
    if (!editing) setDraft(value ?? '');
  }, [value, editing]);

  return (
    <div className="flex items-center gap-2 text-xs">
      <span
        className="shrink-0 w-20 text-right"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        {label}
      </span>
      {editing ? (
        <>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="flex-1 rounded px-1.5 py-0.5 text-xs"
            style={{
              background: 'var(--color-bg-input)',
              color: 'var(--color-text-primary)',
              border: '1px solid var(--color-border)',
            }}
            autoFocus
          />
          <button
            type="button"
            onClick={() => {
              onSave(draft.trim() || null);
              setEditing(false);
            }}
            className="text-[10px] inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded hover:opacity-80"
            style={{ color: 'var(--color-text-secondary)' }}
            title="保存"
          >
            <Check size={11} />
          </button>
          <button
            type="button"
            onClick={() => {
              setDraft(value ?? '');
              setEditing(false);
            }}
            className="text-[10px] inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded hover:opacity-80"
            style={{ color: 'var(--color-text-secondary)' }}
            title="取消"
          >
            <X size={11} />
          </button>
        </>
      ) : (
        <>
          <span
            className="flex-1 truncate"
            style={{
              color: value
                ? 'var(--color-text-primary)'
                : 'var(--color-text-secondary)',
            }}
            title={value ?? ''}
          >
            {value ?? '（未填）'}
          </span>
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="text-[10px] inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded hover:opacity-80"
            style={{ color: 'var(--color-text-secondary)' }}
            title="编辑"
          >
            <Pencil size={11} />
            编辑
          </button>
        </>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// List field (item-level add/remove)
// ---------------------------------------------------------------------------


function ListField({
  label,
  values,
  onSave,
}: {
  label: string;
  values: string[];
  onSave: (v: string[]) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [newItem, setNewItem] = useState('');

  const removeAt = (idx: number) => {
    onSave(values.filter((_, i) => i !== idx));
  };

  const addItem = () => {
    const t = newItem.trim();
    if (!t) {
      setAdding(false);
      return;
    }
    onSave([...values, t]);
    setNewItem('');
    setAdding(false);
  };

  return (
    <div className="flex items-start gap-2 text-xs">
      <span
        className="shrink-0 w-20 text-right pt-0.5"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        {label}
      </span>
      <div className="flex-1 flex flex-wrap gap-1 items-center">
        {values.length === 0 && !adding && (
          <span style={{ color: 'var(--color-text-secondary)' }}>（空）</span>
        )}
        {values.map((v, idx) => (
          <span
            key={`${v}-${idx}`}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px]"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-primary)',
              border: '1px solid var(--color-border-subtle)',
            }}
          >
            {v}
            <button
              type="button"
              onClick={() => removeAt(idx)}
              className="opacity-60 hover:opacity-100"
              title="删除"
            >
              <X size={10} />
            </button>
          </span>
        ))}
        {adding ? (
          <span className="inline-flex items-center gap-1">
            <input
              value={newItem}
              onChange={(e) => setNewItem(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') addItem();
                if (e.key === 'Escape') {
                  setAdding(false);
                  setNewItem('');
                }
              }}
              className="rounded px-1.5 py-0.5 text-xs w-32"
              style={{
                background: 'var(--color-bg-input)',
                color: 'var(--color-text-primary)',
                border: '1px solid var(--color-border)',
              }}
              autoFocus
            />
            <button
              type="button"
              onClick={addItem}
              className="text-[10px] px-1 py-0.5 rounded hover:opacity-80"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <Check size={11} />
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="text-[10px] inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded hover:opacity-80"
            style={{ color: 'var(--color-text-secondary)' }}
            title="添加"
          >
            <Plus size={11} />
            添加
          </button>
        )}
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// ConfirmModal (chunk 9 commit 5 pattern reuse)
// ---------------------------------------------------------------------------


function ConfirmModal({
  text,
  onConfirm,
  onCancel,
}: {
  text: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'color-mix(in srgb, var(--color-bg-base) 60%, transparent)' }}
      onClick={onCancel}
    >
      <div
        className="rounded-lg p-5 w-80 shadow-2xl"
        style={{
          background: 'var(--color-bg-surface)',
          border: '1px solid var(--color-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <p
          className="text-sm mb-4 whitespace-pre-line"
          style={{ color: 'var(--color-text-primary)' }}
        >
          {text}
        </p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-1.5 text-xs rounded-md"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-primary)',
            }}
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-3 py-1.5 text-xs rounded-md bg-rose-600 text-white hover:bg-rose-500"
          >
            确认
          </button>
        </div>
      </div>
    </div>
  );
}

// chunk 9 deleteProfileSummary 调用点已移到 ``UserProfileLegacySection`` (未来
// 删除时使用)。chunk 11 UI 不再暴露 [清空]——靠 [完全重置] 走 LLM 重写来达
// 到"清空"语义，简化用户路径。
void deleteProfileData;  // keep import for future use; silence lint
