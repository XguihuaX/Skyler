/**
 * v4-fan chunk 4 — Character Gallery 全屏入口。
 *
 * 状态机(纯 component-local + 1 个 store flag):
 *   - store.galleryOpen 控制本组件是否 mount(由 TopBar Gallery 按钮 +
 *     Esc / close 按钮 + CTA 切换三处翻动)。
 *   - 内部 ``mode``:'browse' | 'detail',决定是否渲染 detail modal。
 *     selectedCharForDetail 跟着 mode 走,detail 时指当前正在浏览详情
 *     的角色(可能不是 store.currentCharacterId)。
 *
 * 交互流(用户 spec):
 *   1. 入口按钮 → setGalleryOpen(true)、mode=browse、Fan 居中显示
 *      store.currentCharacterId(若有)
 *   2. 浏览 fan(72°/12°)— 点非中心卡 → FanLayout 内部 click handler
 *      已经 setCurrentCharacterId + 圆周旋转过去(Fan-3 已 ship)
 *   3. 点中心卡(currentCharacterId 那张)→ mode=detail
 *      *只有点中心卡才进 detail*。点边卡只是 carousel 旋转,不进 detail。
 *      理由:detail 是"看选中那张",边卡 click 是"我想选那张"。
 *   4. detail 内 close / Esc → mode=browse(不退 Gallery)
 *   5. detail 内 CTA → setCurrentCharacterId(已生效) + setGalleryOpen(false)
 *      → 整个 Gallery 卸载,主 UI Live2D / WS 自动跟随(reactive store)
 *   6. browse 态 close / Esc → setGalleryOpen(false)
 *
 * Hero animation 走 framer-motion shared layoutId。FanLayout 已 wrap
 * cards 在 ``<motion.div layoutId={`fan-card-${id}`}>`` 里;Gallery 的
 * ``hideHeroForId`` prop 控制该卡 browse wrapper 在 hero 期间隐藏。
 *
 * Backdrop:radial-gradient + 顶层 backdrop-blur(由 detail modal 自己加)。
 * Fan-2 spike 已验证 ≥55fps。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';
import { useAppStore } from '../../store';
import FanLayout from './FanLayout';
import CharacterDetailModal from './CharacterDetailModal';

type GalleryMode = 'browse' | 'detail';

export default function CharacterGallery() {
  const open  = useAppStore((s) => s.galleryOpen);
  const setOpen = useAppStore((s) => s.setGalleryOpen);
  const characters = useAppStore((s) => s.characters);
  const currentCharacterId = useAppStore((s) => s.currentCharacterId);
  const setCurrentCharacterId = useAppStore((s) => s.setCurrentCharacterId);

  const [mode, setMode] = useState<GalleryMode>('browse');
  const [detailForId, setDetailForId] = useState<number | null>(null);

  // open=false → reset to browse for next open(避免下次打开还停在 detail)
  useEffect(() => {
    if (!open) {
      setMode('browse');
      setDetailForId(null);
    }
  }, [open]);

  // ESC handler:browse → close gallery;detail → back to browse(交给 modal)
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      // detail modal 自己处理 Esc(优先关 detail);
      // 只有 browse 态才让 Esc 关 gallery
      if (mode === 'browse') {
        setOpen(false);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, mode, setOpen]);

  // FanLayout 的 onSelectCharacter:点边卡 → 仅旋转,不进 detail。
  // 点中心卡(已 selected)→ 进 detail。FanLayout 不区分中心 / 边卡,
  // 都调一次 onSelectCharacter。我们在这里判:click 的卡 id 已等于
  // currentCharacterId → 是中心卡 → 进 detail;否则只是 carousel 旋转。
  const handleSelect = useCallback((id: number) => {
    if (id === currentCharacterId) {
      // 点中心卡 → 进 detail
      setDetailForId(id);
      setMode('detail');
    } else {
      // 点边卡 → 圆周旋转切换(setCurrentCharacterId 让 FanLayout 重新算
      // 最短路径)。不进 detail。
      setCurrentCharacterId(id);
    }
  }, [currentCharacterId, setCurrentCharacterId]);

  const detailChar = useMemo(
    () => (detailForId == null ? null : characters.find((c) => c.id === detailForId) ?? null),
    [detailForId, characters],
  );

  const handleDetailClose = useCallback(() => {
    setMode('browse');
    setDetailForId(null);
  }, []);

  const handleSwitch = useCallback((id: number) => {
    setCurrentCharacterId(id);
    setOpen(false);
    // mode reset 由上面的 open=false useEffect 处理
  }, [setCurrentCharacterId, setOpen]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[990] overflow-hidden"
      style={{
        background:
          'radial-gradient(circle at 50% 60%, '
          + 'var(--color-bg-elevated) 0%, '
          + 'var(--color-bg-surface) 50%, '
          + 'var(--color-bg-base) 100%)',
      }}
    >
      {/* Fan layout(永远渲染,即使 detail open;hero 共享 layoutId 需要
          source 元素仍在树里) */}
      <FanLayout
        characters={characters}
        selectedCharId={currentCharacterId}
        onSelectCharacter={handleSelect}
        hideHeroForId={mode === 'detail' ? detailForId : null}
      />

      {/* Top label */}
      <div
        className="fixed top-3 left-1/2 -translate-x-1/2 px-4 py-1.5 text-xs rounded-full font-medium pointer-events-none"
        style={{
          background:  'color-mix(in srgb, var(--color-bg-surface) 70%, transparent)',
          color:       'var(--color-text-secondary)',
          border:      '1px solid var(--color-border-subtle)',
          backdropFilter:       'blur(6px)',
          WebkitBackdropFilter: 'blur(6px)',
          letterSpacing: '0.05em',
        }}
      >
        角色图鉴 · Character Gallery
      </div>

      {/* Close button(右上)— browse 态退出 gallery;detail 态由 modal
          自己的 close 按钮处理(本按钮在 detail 时被 backdrop-blur 模糊压住) */}
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="fixed top-3 right-3 w-9 h-9 rounded-full flex items-center justify-center transition shadow-lg"
        style={{
          background: 'color-mix(in srgb, var(--color-bg-elevated) 85%, transparent)',
          color:      'var(--color-text-primary)',
          border:     '1px solid var(--color-border)',
          zIndex:     995,
        }}
        title="关闭(Esc)"
      >
        <X size={16} />
      </button>

      {/* Hint(只 browse 态显示) */}
      {mode === 'browse' && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2, duration: 0.35 }}
          className="fixed bottom-6 left-1/2 -translate-x-1/2 text-xs px-3 py-1.5 rounded-full pointer-events-none"
          style={{
            background:  'color-mix(in srgb, var(--color-bg-surface) 70%, transparent)',
            color:       'var(--color-text-secondary)',
            border:      '1px solid var(--color-border-subtle)',
            backdropFilter:       'blur(6px)',
            WebkitBackdropFilter: 'blur(6px)',
          }}
        >
          点边卡切换 · 点中心卡查看详情
        </motion.div>
      )}

      {/* Detail modal(AnimatePresence 让 exit 反向动画) */}
      <AnimatePresence>
        {mode === 'detail' && detailChar && (
          <CharacterDetailModal
            key={`detail-${detailChar.id}`}
            character={detailChar}
            onClose={handleDetailClose}
            onSwitch={handleSwitch}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
