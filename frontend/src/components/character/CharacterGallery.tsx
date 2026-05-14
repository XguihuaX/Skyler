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
  const setCurrentCharacterId = useAppStore((s) => s.setCurrentCharacterId);

  const [mode, setMode] = useState<GalleryMode>('browse');
  const [detailForId, setDetailForId] = useState<number | null>(null);

  // bugfix-2.3: Gallery 浏览态不再自动选中当前角色,改为本地 "centerCharId"
  // 跟踪 fan 中心卡。打开 Gallery 时重置为 characters[0],不读 currentCharacterId
  // (即"我现在用的角色"在 Gallery 内部毫无视觉地位,Gallery 是中性浏览)。
  // 点边卡 → setCenterCharId(只转 fan); 点中心卡 → 进 detail。
  // 切换 active 仅通过 detail modal CTA(handleSwitch)显式触发。
  const [centerCharId, setCenterCharId] = useState<number | null>(null);

  // open=false → reset state for next open(下次打开仍从第一张卡, 不记忆)
  useEffect(() => {
    if (!open) {
      setMode('browse');
      setDetailForId(null);
      setCenterCharId(null);
    } else {
      // On every open transition, force-reset center to first card. 故意不
      // 把 ``characters`` 加进 deps —— Gallery 开启中 characters 列表变化
      // (eg 后台 polling 新角色加进来)不该让 fan 跳回第一张。
      setCenterCharId(characters[0]?.id ?? null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  // bugfix-2.3: 点中心卡(本地 centerCharId)→ 进 detail; 点边卡 → 仅
  // 旋转(setCenterCharId 让 FanLayout 重新算最短路径), 不再 setCurrentCharacterId。
  // 主 UI active 角色只在 detail modal CTA 才会被切, browse 全程不动 global state。
  const handleSelect = useCallback((id: number) => {
    if (id === centerCharId) {
      setDetailForId(id);
      setMode('detail');
    } else {
      setCenterCharId(id);
    }
  }, [centerCharId]);

  const detailChar = useMemo(
    () => (detailForId == null ? null : characters.find((c) => c.id === detailForId) ?? null),
    [detailForId, characters],
  );

  // bugfix-2.3: 动态背景跟随 Gallery 本地中心卡(centerCharId),不再跟全局
  // currentCharacterId。语义:"用户当前在浏览谁,背景就映射谁"——这本来
  // 就是 Fan-4.2 想做的"跟随 selected 卡",只是之前 selected == 全局 active
  // 把概念混淆了。decouple 后真正实现:fan 旋一格 → 背景跨淡到新中心卡的
  // splash art。
  const centerCharacter = useMemo(
    () => characters.find((c) => c.id === centerCharId) ?? null,
    [characters, centerCharId],
  );
  const bgSrc = getBgSrc(centerCharacter);

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
          - filter: blur(14px) brightness(0.4) saturate(1.05)
            Fan-5.2 微调:blur 22 → 14(角色主体微清, "哦这是某个角色"的
            认知钩子);brightness 0.35 → 0.4(blur 减弱后亮度略提补回);
            saturate 1.1 → 1.05(blur 越弱色彩自然度越回归)。
          - object-fit: cover + object-position: center 20% — 让 cover
            裁切偏向显示立绘上半(脸 + 头部, 关键识别区), 而不是腰部。
            标准立绘 2:3 portrait 头部在顶 1/3, 20% 让 cover 把头部锚在
            viewport 上 1/5 而不是切掉。
          - transform: scale(1.0) — Fan-5.1 的 scale(1.1) 防 22px halo
            漏底; blur 14px halo 同步缩小, scale 1.0 也够用, 而且能少
            裁掉一点立绘内容。
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
            objectPosition: 'center 20%',
            transform: 'scale(1.0)',
            filter:       'blur(14px) brightness(0.4) saturate(1.05)',
            WebkitFilter: 'blur(14px) brightness(0.4) saturate(1.05)',
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
          selectedCharId={centerCharId}
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
