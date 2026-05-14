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
 * v4-fan chunk 4.2 — 动态背景:跟随 selected 角色的 splash_art 模糊放大版
 * 铺满全屏。无 splash 用 ``/splash-art/_placeholder.png``。切角色时用
 * AnimatePresence + key=src 做交叉淡化(0.6s),兼顾"软切角色"质感和"
 * 跟 detail modal 的 backdrop-blur(8px) 叠乘"的视觉合成。性能:Fan-2
 * spike 验证 backdrop-blur(8) ≥55fps;本层是 ``filter: blur(40px)`` 不是
 * backdrop,在 WKWebView 上更便宜(单层 raster cache),不退化。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';
import { useAppStore } from '../../store';
import FanLayout from './FanLayout';
import CharacterDetailModal from './CharacterDetailModal';

type GalleryMode = 'browse' | 'detail';

// 兜底立绘(splash_art_url 为 null / 空 / 加载失败时用)。Fan-1 backend
// 写死路径,Fan-2 PIL 生成 1024×1536 灰图。CharacterCard 同 pattern。
const PLACEHOLDER_BG = '/splash-art/_placeholder.png';

function getBgSrc(c: { splash_art_url: string | null } | null): string {
  if (c?.splash_art_url && c.splash_art_url.trim()) return c.splash_art_url;
  return PLACEHOLDER_BG;
}

// v4-fan chunk 4.4:重新引入 URL query 调参(Fan-4 retire ?fan=1 时一并
// 删了导致 ?cy=2000 等不再生效——用户 Fan-4.3 之后的"cy 没生效"诊断
// 实际就是这个回归)。module scope 一次解析,Gallery 每次 mount 复用。
//
//   ?vc=5     visibleCount = 5
//   ?r=750    radius = 750
//   ?arc=90   arcDegree = 90
//   ?dur=300  transitionDuration = 300
//   ?cy=2000  centerOffsetY = 2000(完全 override 默认公式)
//   ?debug=1  FanLayout debug overlay + console diagnostic 全开
const _GALLERY_QUERY = (() => {
  if (typeof window === 'undefined') {
    return { debug: false, layoutParams: undefined as undefined };
  }
  const sp = new URLSearchParams(window.location.search);
  const numOrUndef = (key: string): number | undefined => {
    const v = sp.get(key);
    if (v == null) return undefined;
    const n = Number(v);
    return Number.isFinite(n) ? n : undefined;
  };
  const lp = {
    visibleCount:       numOrUndef('vc'),
    radius:             numOrUndef('r'),
    arcDegree:          numOrUndef('arc'),
    transitionDuration: numOrUndef('dur'),
    centerOffsetY:      numOrUndef('cy'),
  };
  // 如果所有 layout 参数都没传 → undefined,让 FanLayout 走纯默认
  const hasAny = Object.values(lp).some((v) => v !== undefined);
  return {
    debug: sp.get('debug') === '1',
    layoutParams: hasAny
      ? Object.fromEntries(Object.entries(lp).filter(([, v]) => v !== undefined))
      : undefined,
  };
})();

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

  // v4-fan chunk 4.2: 动态背景源 = selected 角色的 splash art。
  // currentCharacterId 变 → bgSrc 变 → AnimatePresence key 变 → 老 img
  // exit (opacity 1→0) + 新 img enter (opacity 0→1) = 交叉淡化 0.6s。
  // detail mode 时也跟 selected 走 (用户在 fan 上点不同卡再进 detail 的
  // 罕见路径会让背景同步变,符合"detail 是 selected 的详情"语义)。
  const selectedCharacter = useMemo(
    () => characters.find((c) => c.id === currentCharacterId) ?? null,
    [characters, currentCharacterId],
  );
  const bgSrc = getBgSrc(selectedCharacter);

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
      // 兜底 base 色:bg img 加载失败极端 case 下不漏 OS 透明窗口
      style={{ background: 'var(--color-bg-base)' }}
    >
      {/* z=0:动态背景层 — splash art 模糊放大版 + 交叉淡化。
          - filter: blur(22px) brightness(0.35) saturate(1.1)
            Fan-5.1 微调:blur 40 → 22(留主体轮廓 + 纹理朦胧感, 不再
            完全色块化);brightness 0.4 → 0.35(轮廓回来后多压一档亮度
            防抢前景卡);saturate 1.2 → 1.1(blur 减弱后色彩自然度回归,
            不需补这么多)。
          - object-fit: cover + scale(1.1) — cover 铺满 viewport,scale 1.1
            防 blur 边缘 (~22px halo) 露出 viewport 边沿(blur 减弱后 halo
            也缩小, 但 1.1 仍稳妥)。
          - AnimatePresence + motion.img key={src} → 切角色时老 img exit
            opacity 1→0 / 新 img enter 0→1, 同时存在 0.6s = 交叉淡化。
            framer-motion 自动 mount/unmount + cleanup。
          - onError: 单图加载失败 → 兜底 _placeholder.png(继承 CharacterCard
            pattern,bg src 已 placeholder 时也不会进死循环 src ===)
          - loading=eager:首屏立即加载,不等 lazy 触发(背景需要立即可见) */}
      <AnimatePresence>
        <motion.img
          key={bgSrc}
          src={bgSrc}
          alt=""
          loading="eager"
          decoding="async"
          draggable={false}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.6, ease: 'easeInOut' }}
          onError={(e) => {
            const el = e.currentTarget;
            if (!el.src.endsWith(PLACEHOLDER_BG)) el.src = PLACEHOLDER_BG;
          }}
          style={{
            position: 'absolute',
            inset: 0,
            width:  '100%',
            height: '100%',
            objectFit: 'cover',
            objectPosition: 'center center',
            transform: 'scale(1.1)',
            filter:       'blur(22px) brightness(0.35) saturate(1.1)',
            WebkitFilter: 'blur(22px) brightness(0.35) saturate(1.1)',
            zIndex: 0,
            pointerEvents: 'none',
            userSelect: 'none',
            willChange: 'opacity',
          }}
        />
      </AnimatePresence>

      {/* z=1:Fan layout(永远渲染,即使 detail open;hero 共享 layoutId
          需要 source 元素仍在树里) */}
      <div className="absolute inset-0" style={{ zIndex: 1 }}>
        <FanLayout
          characters={characters}
          selectedCharId={currentCharacterId}
          onSelectCharacter={handleSelect}
          hideHeroForId={mode === 'detail' ? detailForId : null}
          layoutParams={_GALLERY_QUERY.layoutParams}
          debug={_GALLERY_QUERY.debug}
        />
      </div>

      {/* z=2:top label */}
      <div
        className="fixed top-3 left-1/2 -translate-x-1/2 px-4 py-1.5 text-xs rounded-full font-medium pointer-events-none"
        style={{
          background:  'color-mix(in srgb, var(--color-bg-surface) 70%, transparent)',
          color:       'var(--color-text-secondary)',
          border:      '1px solid var(--color-border-subtle)',
          backdropFilter:       'blur(6px)',
          WebkitBackdropFilter: 'blur(6px)',
          letterSpacing: '0.05em',
          zIndex: 2,
        }}
      >
        角色图鉴 · Character Gallery
      </div>

      {/* z=2:close button(右上)— browse 态退出 gallery;detail 态由 modal
          自己的 close 按钮处理(本按钮在 detail 时被 backdrop-blur 模糊压住) */}
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="fixed top-3 right-3 w-9 h-9 rounded-full flex items-center justify-center transition shadow-lg"
        style={{
          background: 'color-mix(in srgb, var(--color-bg-elevated) 85%, transparent)',
          color:      'var(--color-text-primary)',
          border:     '1px solid var(--color-border)',
          zIndex:     2,
        }}
        title="关闭(Esc)"
      >
        <X size={16} />
      </button>

      {/* z=2:hint(只 browse 态显示) */}
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
            zIndex: 2,
          }}
        >
          点边卡切换 · 点中心卡查看详情
        </motion.div>
      )}

      {/* z=1000+:Detail modal(modal 内部已设 z=1000/1001;不冲突 Gallery 内 z 栈) */}
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
