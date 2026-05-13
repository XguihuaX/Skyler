/**
 * v4-fan chunk 3.2 — 紧凑 fan + 统一 stepDeg。
 *
 * Fan-3.1 用户实测后反馈"5 角色 / arc=120 / vc=7 间距仍大"。本 iter:
 *
 * **统一 stepDeg 公式**:不分大小 N,一律 ``stepDeg = arcDeg / (W - 1)``。
 * 删 Fan-3.1 的 N ≤ visibleCount 用 ``arcDeg/(N-1)`` 撑满弧的特殊路径。
 *
 * 后果(也是用户拍板的视觉目标):
 *   - **N < W**:fan 撑开 ``(N-1) × stepDeg`` 度,**不强制占满 arcDeg**。
 *     视觉上少卡时 fan 紧凑居中,不会摊开成"几个孤立卡漂浮"。
 *   - **N ≥ W**:窗口 fan 撑开 arcDeg,与 Fan-3.1 一致。
 *   - **任意 N 卡间距相同**(都 = stepDeg),不会"少卡时大、多卡时小"——
 *     这是 Fan-3.1 跟 Fan-3.2 用户体感上最重要的差别。
 *
 * **默认 arcDegree**:120 → 60(stepDeg 默认 10°)。卡 160px @ R=600
 * 角宽 ≈ 15°,stepDeg=10° 让相邻卡 ~30-50% 重叠,扇面紧凑。要更松调
 * ``?arc=90``;要更紧 ``?arc=40``。
 *
 * 渲染分支(只决定渲染哪几张卡,跟 stepDeg 无关):
 *   - **N > W**:仅窗口内 W 张(selected ± floor(W/2)),DOM 上不存在窗
 *     外卡;React key=character.id,持续在窗口的卡 base 不变 → 容器 rotate
 *     平滑无 jump。
 *   - **N ≤ W**:渲染所有 N 张;N=1 单卡居中。
 *
 * 360° 圆周语义保留(currentIndex unbounded + 最短路径 click + 容器
 * rotate(-currentIndex × stepDeg))。
 *
 * 已知视觉折衷:
 *   1. 窗口边缘卡 (offset = ±W/2) displayed = ±arcDeg/2 = fade boundary,
 *      opacity=1。click 时 leading/trailing 卡 mount/unmount 有"pop"。
 *      当前 spec 不加 buffer,接受。要更平滑的 fade 提示"还有更多",
 *      未来 Fan-3.3 加 1-2 buffer cards each side。
 *   2. 小 N (N ≤ W) case 的 "back card":currentIndex 改变时,处于"绕远端"
 *      的卡 offset 会从 -N/2 wrap 到 +N/2,该卡 base 跳变,wrapper left/top
 *      snap。Fan-3.2 stepDeg 变小后,跳变绝对值也变小(N=5 wrap 跳 4*10°=
 *      40° vs Fan-3.1 60°),且发生在 ±20° 视野内(Fan-3.1 是 ±30°),
 *      可见性反而稍提升 — 但仍在 spec 容忍范围。
 */
import { useEffect, useMemo, useState } from 'react';
import CharacterCard from './CharacterCard';
import type { CharacterRow } from '../../lib/config';

export interface FanLayoutParams {
  /** 圆周半径 px。默认 600。 */
  radius: number;
  /** 圆心 Y(从视口顶起算)。默认 ``window.innerHeight + 100``。 */
  centerOffsetY: number;
  /**
   * 可见弧度数 (中心 ±arcDeg/2 内 opacity=1,外侧 fade)。
   * **默认 60** (Fan-3.2:120 → 60,紧凑 fan)。stepDeg 派生:
   * ``arcDeg / (visibleCount - 1)`` = 60/6 = 10° (默认 W=7)。
   */
  arcDegree: number;
  /** Container 旋转 + opacity transition 毫秒。默认 500。 */
  transitionDuration: number;
  /**
   * 可见窗口大小。**必须奇数 ≥ 3** (selected + 对称左右各 (W-1)/2)。
   * 默认 7 (selected + 左右各 3)。偶数会向上凑奇,< 3 钳到 3,都
   * ``console.warn``。
   *
   * Fan-3.2 默认 (arcDeg=60, vc=7) → stepDeg=10°,卡 160px @ R=600 角宽
   * ≈ 15°,相邻卡 ~30-50% 重叠。
   *
   * sweep 矩阵参考:
   *   - vc=5, arc=60: stepDeg=15°,3 卡密集 + 2 边缘 (无重叠)
   *   - vc=7, arc=60 ⭐: stepDeg=10°,5 卡密集 + 2 边缘 (重叠)
   *   - vc=9, arc=60: stepDeg=7.5°,7 卡密集 + 2 边缘 (重重叠)
   */
  visibleCount: number;
}

interface FanLayoutProps {
  characters: CharacterRow[];
  selectedCharId: number | null;
  onSelectCharacter: (id: number) => void;
  layoutParams?: Partial<FanLayoutParams>;
  debug?: boolean;
}

const MIN_OPACITY = 0.15;
const CARD_W = 160;
const CARD_H = 240;

function shortestDelta(target: number, current: number, n: number): number {
  if (n <= 1) return 0;
  const offset = target - current + n / 2;
  const mod = ((offset % n) + n) % n;
  return mod - n / 2;
}

function normalizeAngle(deg: number): number {
  let a = deg % 360;
  if (a > 180) a -= 360;
  if (a < -180) a += 360;
  return a;
}

function fadeOpacity(displayedDeg: number, arcDeg: number): number {
  const absD = Math.abs(normalizeAngle(displayedDeg));
  const half = arcDeg / 2;
  if (absD <= half) return 1;
  const range = 180 - half;
  if (range <= 0) return MIN_OPACITY;
  const t = (absD - half) / range;
  return Math.max(MIN_OPACITY, 1 - t * (1 - MIN_OPACITY));
}

function posMod(value: number, n: number): number {
  return ((value % n) + n) % n;
}

function normalizeVisibleCount(raw: number): number {
  let v = Math.max(3, Math.floor(raw));
  if (v % 2 === 0) {
    // eslint-disable-next-line no-console
    console.warn(
      `[FanLayout] visibleCount must be odd (got ${raw}), rounded up to ${v + 1}`,
    );
    v += 1;
  }
  return v;
}

interface CardSpot {
  charIdx: number;
  /** 距 selected 的视觉 offset (displayed angle = offset × stepDeg)。 */
  offset: number;
}

/**
 * Fan-3.2:**stepDeg 统一**(去掉 N ≤ W 的撑满弧特殊路径)。
 *
 * stepDeg = arcDeg / (visibleCount - 1) 永远成立,跟 N 无关。
 * 渲染分支只决定**哪几张卡**进 DOM:
 *   - N ≤ W:全部 N 卡,offset 由 shortestDelta 算 (允许 wrap)
 *   - N > W:窗口 W 卡,offset = [-half..+half]
 *
 * 后果:N < W 时 fan 撑开 (N-1) × stepDeg 度,**不强制占满 arcDeg** —
 * 视觉上少卡时紧凑居中而非"几个孤立卡撑开"。
 */
function computeSpots(
  n: number,
  currentMod: number,
  visibleCount: number,
  arcDegree: number,
): { stepDeg: number; spots: CardSpot[]; mode: 'all' | 'windowed' } {
  if (n === 0) return { stepDeg: 0, spots: [], mode: 'all' };

  // 统一 stepDeg(N=1 时算出来无意义,反正只一卡也不用)
  const stepDeg = arcDegree / (visibleCount - 1);

  if (n === 1) {
    return { stepDeg, spots: [{ charIdx: 0, offset: 0 }], mode: 'all' };
  }

  if (n <= visibleCount) {
    const spots: CardSpot[] = [];
    for (let i = 0; i < n; i++) {
      spots.push({ charIdx: i, offset: shortestDelta(i, currentMod, n) });
    }
    return { stepDeg, spots, mode: 'all' };
  }

  const half = Math.floor(visibleCount / 2);
  const spots: CardSpot[] = [];
  for (let o = -half; o <= half; o++) {
    spots.push({ charIdx: posMod(currentMod + o, n), offset: o });
  }
  return { stepDeg, spots, mode: 'windowed' };
}

export default function FanLayout({
  characters,
  selectedCharId,
  onSelectCharacter,
  layoutParams,
  debug = false,
}: FanLayoutProps) {
  const [viewportH, setViewportH] = useState(
    typeof window !== 'undefined' ? window.innerHeight : 800,
  );
  useEffect(() => {
    const onResize = () => setViewportH(window.innerHeight);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const params: FanLayoutParams = useMemo(() => {
    const rawVC = layoutParams?.visibleCount ?? 7;
    return {
      radius:             layoutParams?.radius             ?? 600,
      centerOffsetY:      layoutParams?.centerOffsetY      ?? viewportH + 100,
      arcDegree:          layoutParams?.arcDegree          ?? 60,
      transitionDuration: layoutParams?.transitionDuration ?? 500,
      visibleCount:       normalizeVisibleCount(rawVC),
    };
  }, [layoutParams, viewportH]);

  const N = characters.length;

  const [currentIndex, setCurrentIndex] = useState<number>(() => {
    if (selectedCharId == null || N === 0) return 0;
    const idx = characters.findIndex((c) => c.id === selectedCharId);
    return idx >= 0 ? idx : 0;
  });

  useEffect(() => {
    if (N === 0 || selectedCharId == null) return;
    const target = characters.findIndex((c) => c.id === selectedCharId);
    if (target < 0) return;
    setCurrentIndex((prev) => {
      const prevMod = posMod(prev, N);
      if (prevMod === target) return prev;
      const delta = shortestDelta(target, prevMod, N);
      return prev + delta;
    });
  }, [selectedCharId, characters, N]);

  if (N === 0) return null;

  const currentMod = posMod(currentIndex, N);
  const { stepDeg, spots, mode } = computeSpots(
    N, currentMod, params.visibleCount, params.arcDegree,
  );

  // Container rotation:用 stepDeg (分支后值) 而非 360/N。这样 click 一格
  // = 容器转 stepDeg = displayed 移一格,跟可见 fan 的视觉一致。
  const containerRotate = -currentIndex * stepDeg;

  return (
    <div className="fixed inset-0 overflow-hidden pointer-events-none">
      {debug && (
        <DebugOverlay
          centerOffsetY={params.centerOffsetY}
          radius={params.radius}
          arcDegree={params.arcDegree}
          stepDeg={stepDeg}
          n={N}
          visibleCount={params.visibleCount}
          currentMod={currentMod}
          mode={mode}
        />
      )}

      <div
        className="absolute"
        style={{
          left:   '50%',
          top:    params.centerOffsetY,
          width:  0,
          height: 0,
          transform:        `rotate(${containerRotate}deg)`,
          transformOrigin:  '0 0',
          transition:       `transform ${params.transitionDuration}ms cubic-bezier(0.22, 1, 0.36, 1)`,
          willChange:       'transform',
        }}
      >
        {spots.map(({ charIdx, offset }) => {
          const c = characters[charIdx];
          if (!c) return null;
          // base = (currentIndex + offset) × stepDeg。container rotate
          // -currentIndex × stepDeg 后,屏幕 displayed = offset × stepDeg。
          //
          // 窗口模式下,window 内持续存在的 character 其 base 不变 (currentIndex
          // 加 1 时,offset 减 1,加减抵消) → 容器 rotate 平滑带它们走;
          // 不在 transition 期间触发 left/top 变化,无 jump。
          //
          // 小 N 模式下,wrap card 的 offset 会跨 -N/2 ↔ +N/2,base 跳变,
          // wrapper left/top 也跳变 (无 transition) → 该卡瞬间从 arc 一边
          // 跳到另一边。视觉上发生在 fade 远端,容忍度高。
          const base = (currentIndex + offset) * stepDeg;
          const rad = (base * Math.PI) / 180;
          const x = params.radius * Math.sin(rad);
          const y = -params.radius * Math.cos(rad);
          const displayed = offset * stepDeg;
          const opacity = fadeOpacity(displayed, params.arcDegree);
          const isSelected = offset === 0;

          return (
            <div
              key={c.id}
              className="absolute"
              style={{
                left:    x - CARD_W / 2,
                top:     y - CARD_H,
                opacity,
                transition:    `opacity ${params.transitionDuration}ms ease-out`,
                pointerEvents: 'auto',
                willChange:    'opacity',
              }}
            >
              <CharacterCard
                character={c}
                variant="browse"
                rotation={base}
                selected={isSelected}
                onClick={() => {
                  setCurrentIndex((prev) => {
                    const prevMod = posMod(prev, N);
                    if (prevMod === charIdx) return prev;
                    const delta = shortestDelta(charIdx, prevMod, N);
                    return prev + delta;
                  });
                  onSelectCharacter(c.id);
                }}
              />
              {debug && (
                <div
                  className="absolute font-mono text-[10px] whitespace-nowrap pointer-events-none"
                  style={{
                    top:    -16,
                    left:   0,
                    color:  '#fff',
                    background:   'rgba(0,0,0,0.7)',
                    padding:      '1px 4px',
                    borderRadius: 2,
                  }}
                >
                  c={c.id} off={offset.toFixed(1)} disp={normalizeAngle(displayed).toFixed(0)}°
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Debug overlay
// ---------------------------------------------------------------------------

interface DebugOverlayProps {
  centerOffsetY: number;
  radius: number;
  arcDegree: number;
  stepDeg: number;
  n: number;
  visibleCount: number;
  currentMod: number;
  mode: 'all' | 'windowed';
}

function DebugOverlay({
  centerOffsetY, radius, arcDegree, stepDeg, n, visibleCount, currentMod, mode,
}: DebugOverlayProps) {
  const half = Math.floor(visibleCount / 2);
  const lo = posMod(currentMod - half, n);
  const hi = posMod(currentMod + half, n);

  return (
    <>
      {/* circle center */}
      <div
        className="absolute pointer-events-none"
        style={{
          left:      '50%',
          top:       centerOffsetY,
          width:     10,
          height:    10,
          transform: 'translate(-50%, -50%)',
          background:   'red',
          borderRadius: '50%',
          zIndex: 100,
        }}
        title="circle center"
      />
      {/* arc edge markers at ±arcDegree/2 */}
      {[+arcDegree / 2, -arcDegree / 2].map((edge) => {
        const rad = (edge * Math.PI) / 180;
        const x = radius * Math.sin(rad);
        const y = -radius * Math.cos(rad);
        return (
          <div
            key={edge}
            className="absolute pointer-events-none font-mono text-[9px]"
            style={{
              left:        `calc(50% + ${x}px)`,
              top:         centerOffsetY + y,
              transform:   'translate(-50%, -50%)',
              color:       '#0ff',
              background:  'rgba(0,0,0,0.65)',
              padding:     '1px 4px',
              borderRadius: 2,
              border:      '1px dashed #0ff',
              zIndex:      100,
            }}
          >
            arc {edge > 0 ? '+' : ''}{edge.toFixed(0)}°
          </div>
        );
      })}
      {/* HUD */}
      <div
        className="fixed bottom-3 left-3 font-mono text-[10px] rounded px-2 py-1 pointer-events-none"
        style={{
          color:       '#fff',
          background:  'rgba(0,0,0,0.78)',
          maxWidth:    420,
          lineHeight:  1.55,
          zIndex:      100,
        }}
      >
        FanLayout debug<br />
        N={n}, mode={mode}, stepDeg={stepDeg.toFixed(1)}°, arcDeg={arcDegree}°<br />
        visibleCount={visibleCount}, currentMod={currentMod}<br />
        {mode === 'windowed'
          ? `window: idx[${lo}..${hi}] of [0..${n - 1}] (W=${visibleCount})`
          : `all-N: idx[0..${n - 1}], no window (N ≤ visibleCount)`}
      </div>
    </>
  );
}
