/**
 * v4-fan chunk 3.1 — Pseudo-circle 可见窗口。
 *
 * Fan-3 改动点(用户实测后反馈"间距太大,角色少时弧太疏"):
 *   - stepDeg 不再用 ``360 / N``。改为按可见 fan 平均分配 ``arcDeg/(W-1)``,
 *     其中 W = ``visibleCount``(默认 7,selected + 左右各 3)。
 *   - **N > visibleCount**:仅渲染窗口内 visibleCount 张卡(以 selected
 *     为中心,左右各 floor(W/2));窗口外不存在 DOM 节点。
 *   - **N ≤ visibleCount**:渲染所有 N 张,stepDeg = ``arcDeg/(N-1)``;
 *     N=1 时单卡居中。
 *
 * 360° 圆周语义保留(currentIndex unbounded + 最短路径 click + 容器
 * rotate(-currentIndex × stepDeg))。窗口化只影响"渲染哪几张卡"和
 * "stepDeg 怎么算",其它一切不变。
 *
 * 已知视觉折衷:
 *   1. 窗口边缘卡 (offset = ±W/2) displayed = ±arcDeg/2,落在 fade
 *      boundary,opacity 是 1。click 时 leading/trailing 卡 mount/unmount
 *      会有 "pop"。当前 spec 不加 buffer,接受这个 pop。要更平滑的 fade
 *      提示"还有更多",见 Fan-3.2 backlog 里 buffer 路径。
 *   2. 小 N (N ≤ visibleCount) case 的 "back card":currentIndex 改变时,
 *      处于"绕远端"的卡 offset 会从 -N/2 wrap 到 +N/2,该卡 base 角度
 *      跳变。容器 rotation 平滑,但该卡的位置 (left/top) 瞬间 snap 到
 *      新位置。实际可见性低 (跳变发生在 arc 远端 fade 区),容忍度高,
 *      用户可见后再决定是否值得修。
 */
import { useEffect, useMemo, useState } from 'react';
import CharacterCard from './CharacterCard';
import type { CharacterRow } from '../../lib/config';

export interface FanLayoutParams {
  /** 圆周半径 px。默认 600。 */
  radius: number;
  /** 圆心 Y(从视口顶起算)。默认 ``window.innerHeight + 100``。 */
  centerOffsetY: number;
  /** 可见弧度数 (中心 ±arcDeg/2 内 opacity=1,外侧 fade)。默认 120 (±60°)。 */
  arcDegree: number;
  /** Container 旋转 + opacity transition 毫秒。默认 500。 */
  transitionDuration: number;
  /**
   * v3.1: 可见窗口大小。**必须奇数 ≥ 3** (selected + 对称左右各
   * (W-1)/2)。默认 7 (selected + 左右各 3)。偶数会向上凑奇,< 3 钳到 3,
   * 都 ``console.warn``。
   *
   * 为什么默认 7:
   *   - 5 张:edge stepDeg = arcDeg/4 = 30°,边缘卡在 ±60° 弧 boundary。
   *     视觉密度低,但中心几张卡间距大 (感觉"卡漂浮")。
   *   - 7 张:stepDeg = 20°,中心 5 张密集 + 边缘 2 张可见提示"还有"。
   *     是密度 / 信息量平衡点。
   *   - 9 张:stepDeg = 15°,中心拥挤,边缘卡几乎贴在一起。
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
 * 决定渲染哪些卡 + stepDeg。两条分支:
 *   - N ≤ W:渲染所有 N 卡,stepDeg = arcDeg/(N-1),offset 由 shortestDelta
 *     算 (允许小 N case 的 wrap)
 *   - N > W:渲染窗口 W 卡,stepDeg = arcDeg/(W-1),offset = [-half..+half]
 */
function computeSpots(
  n: number,
  currentMod: number,
  visibleCount: number,
  arcDegree: number,
): { stepDeg: number; spots: CardSpot[]; mode: 'all' | 'windowed' } {
  if (n === 0) return { stepDeg: 0, spots: [], mode: 'all' };
  if (n === 1) return { stepDeg: 0, spots: [{ charIdx: 0, offset: 0 }], mode: 'all' };

  if (n <= visibleCount) {
    const stepDeg = arcDegree / (n - 1);
    const spots: CardSpot[] = [];
    for (let i = 0; i < n; i++) {
      spots.push({ charIdx: i, offset: shortestDelta(i, currentMod, n) });
    }
    return { stepDeg, spots, mode: 'all' };
  }

  const stepDeg = arcDegree / (visibleCount - 1);
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
      arcDegree:          layoutParams?.arcDegree          ?? 120,
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
