/**
 * v4-fan chunk 2 — Fan UI 卡牌单卡 primitive。
 *
 * 设计原则:**图本身是艺术品**(参考用户给的丰川翔子立绘范本)——卡牌
 * 极简,no border / no caption / no badge / no rarity ribbon。装饰一律
 * 由 splash art 自身承担,组件只管:
 *   - 加载 splash_art_url(null → _placeholder.png 兜底)
 *   - 接 fan layout 传入的 rotation + position(纯 CSS transform)
 *   - selected 态做"中心高亮"(scale + 去 desaturate + 去 dim + 抬阴影)
 *   - detail 态:同 img,无旋转,2.5x 尺寸
 *
 * 性能契约(P0):
 *   - 不在卡片自身用 backdrop-filter(8 张同时 = WKWebView GPU 灾难,见
 *     docs/fan-ui-starting-context.md §9 P0)。背景模糊由 FanLayout 单
 *     overlay 层承担,本组件只管 transform / filter。
 *   - <img> 加 ``loading="lazy"`` + ``decoding="async"``,首次扇面展开时
 *     8 张并发 decode 不阻塞主线程。
 *
 * Q-decisions(audit §7):
 *   - Q1 动画:纯 CSS transform / transition,无 framer-motion(留 Fan-4 用)
 *   - Q5 fallback:`/splash-art/_placeholder.png`(单张静态;Fan-1 已 ship 该路径)
 *   - Q8 卡牌底图:splash art(无图回 placeholder,不用 Live2D 截图)
 */
import type { CSSProperties } from 'react';
import type { CharacterRow } from '../../lib/config';

const PLACEHOLDER_URL = '/splash-art/_placeholder.png';

// 2:3 卡牌比(原神 / FGO 系标准)。browse 紧凑,detail 放大约 2.5x。
const SIZE_BROWSE  = { w: 160, h: 240 } as const;
const SIZE_DETAIL  = { w: 400, h: 600 } as const;

export interface CharacterCardProps {
  character: CharacterRow;
  variant: 'browse' | 'detail';
  /** 度数,默认 0;detail 态忽略。Fan layout 传入 each-card 角度。 */
  rotation?: number;
  /**
   * Fan layout 算好的位置(transform translate)+ 缩放。
   * - x / y: px,相对 layout 容器中心
   * - scale: 1 = 正常;layout 可对侧卡传 0.95 之类
   *
   * 与 ``selected`` 的 1.15 倍是**乘法叠加**:layout 算几何,selected 加
   * "突出"。这样允许 layout 自己做 perspective scale 而不冲突。
   */
  position?: { x: number; y: number; scale: number };
  selected?: boolean;
  onClick?: () => void;
}

export default function CharacterCard({
  character,
  variant,
  rotation = 0,
  position,
  selected = false,
  onClick,
}: CharacterCardProps) {
  const isBrowse = variant === 'browse';
  const dim = isBrowse ? SIZE_BROWSE : SIZE_DETAIL;

  // splash 兜底:null / 空串 / 仅空白都视作"未配置",走 placeholder
  const splashSrc =
    character.splash_art_url && character.splash_art_url.trim()
      ? character.splash_art_url
      : PLACEHOLDER_URL;

  // -------------------------------------------------------------------------
  // Transform 计算
  //
  // detail:无旋转、无 layout position;直接居中放大用 wrapper 自己的 layout。
  // browse:layout 几何 (x/y/scale) × selected 高亮 (scale 1.15) × rotation。
  //
  // transform 顺序很关键:translate 先(决定弧上位置)→ rotate 后(让卡片
  // 沿弧切线翻)。如果 rotate 在前,translate 会被旋转后的坐标系扭。
  // -------------------------------------------------------------------------
  const layoutScale = position?.scale ?? 1;
  const selectedBoost = selected && isBrowse ? 1.15 : 1;
  const finalScale = layoutScale * selectedBoost;

  const transform = isBrowse
    ? [
        position ? `translate(${position.x}px, ${position.y}px)` : '',
        rotation ? `rotate(${rotation}deg)` : '',
        finalScale !== 1 ? `scale(${finalScale})` : '',
      ]
        .filter(Boolean)
        .join(' ') || 'none'
    : 'none';

  // -------------------------------------------------------------------------
  // Filter:非 selected 在 browse 态轻微"去强调"——desaturate 0.7 + 调暗
  // 0.85。中心 selected 卡保持原色 + 原亮度,自然吸引视觉焦点。
  // detail 态永远是焦点,不 filter。
  // -------------------------------------------------------------------------
  const filter =
    isBrowse && !selected
      ? 'saturate(0.7) brightness(0.85)'
      : 'none';

  // -------------------------------------------------------------------------
  // 阴影:rest / lift。selected 走 lift,其余 rest。Fan-3 hover 也走 lift
  // (CSS hover 选择器叠加;此处先把 prop-driven 通路立起)。
  // -------------------------------------------------------------------------
  const boxShadow = selected
    ? 'var(--shadow-card-lift)'
    : 'var(--shadow-card-rest)';

  const wrapperStyle: CSSProperties = {
    width:  `${dim.w}px`,
    height: `${dim.h}px`,
    transform,
    filter,
    boxShadow,
    background: 'var(--gradient-card-default)',
    transformOrigin: isBrowse ? 'bottom center' : 'center',
    // 切换 selected 时所有视觉属性同步 ease。0.35s 是"够看清变化但不拖
    // 沓"的体感值;Fan-3 调试时再微调。
    transition:
      'transform 0.35s cubic-bezier(0.22, 1, 0.36, 1), '
      + 'filter 0.35s ease-out, '
      + 'box-shadow 0.35s ease-out',
    // 渲染层提示:browse 态下 8 张卡同时 transform,提前 hint composite
    // layer 减少首次 paint 抖动。detail 不需要(只一张)。
    willChange: isBrowse ? 'transform, filter' : 'auto',
  };

  return (
    <div
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      aria-label={`角色:${character.name}`}
      onClick={onClick}
      onKeyDown={(e) => {
        if (onClick && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault();
          onClick();
        }
      }}
      className="relative rounded-2xl overflow-hidden cursor-pointer select-none"
      style={wrapperStyle}
    >
      <img
        src={splashSrc}
        alt={character.name}
        draggable={false}
        loading="lazy"
        decoding="async"
        className="w-full h-full select-none pointer-events-none"
        style={{
          objectFit: 'cover',
          objectPosition: 'center top',
          // Webkit drag ghost 抑制;CharacterView.tsx:176 同 pattern
          ...({ WebkitUserDrag: 'none' } as unknown as CSSProperties),
        }}
        // src 失败(404 / 网络)时硬切到 placeholder。避免单角色立绘文件
        // 被手动删后整张卡变 broken-image icon。
        onError={(e) => {
          const el = e.currentTarget;
          if (el.src.endsWith(PLACEHOLDER_URL)) return;
          el.src = PLACEHOLDER_URL;
        }}
      />
    </div>
  );
}
