/**
 * v4-fan chunk 3 — Model A 圆周转盘 layout。
 *
 * 几何(audit §6.3 + 用户拍板):
 *   - N 张卡均匀 360° 圆周,每张占 stepDeg = 360/N
 *   - 圆心:屏幕水平中央 + 视口底部下方 ``centerOffsetY``(默认 H+100)
 *   - 极坐标 (R, θ) → 笛卡尔 (R·sin θ, -R·cos θ)
 *   - 卡片自然倾斜跟随圆周(自身 ``rotate(θ_i)`` + transform-origin: bottom center)
 *   - top (displayed θ = 0) = selected
 *
 * 转动机制(单一旋转源):
 *   - **axis 容器**整体 ``rotate(-currentIndex × stepDeg)``
 *   - 每张卡 absolute 定位在固定 (x_i, y_i),CharacterCard 内部 ``rotate(θ_i)``
 *   - axis rotate 后,card_i 的屏幕显示角 = (i - currentIndex) × stepDeg
 *   - card_i = currentIndex 时显示角 = 0(top,vertical,selected)
 *
 * 点击切换(最短路径):
 *   - delta = ((target - current + N/2) mod N) - N/2  ∈ [-N/2, N/2)
 *   - currentIndex 不归一(允许 unbounded 累积),保证 N 张卡里点距离最远
 *     的那张也走 ≤ 半周转;而非 359° vs -1° 这种远绕
 *   - container CSS transition 自然产出短路径转动效果
 *
 * 可调参数(props.layoutParams):为 Fan-6 polish sweep 留口
 *   - radius / centerOffsetY / arcDegree / transitionDuration 全 expose
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import CharacterCard from './CharacterCard';
import type { CharacterRow } from '../../lib/config';

export interface FanLayoutParams {
  /** 圆周半径 px。默认 600。 */
  radius: number;
  /**
   * 圆心 Y 坐标(从视口顶起算),px。默认 ``window.innerHeight + 100``
   * (屏幕底部下方 100 px,让可见弧位于屏幕上方)。
   */
  centerOffsetY: number;
  /**
   * 可见弧度数(中心 ±arcDegree/2 内 opacity=1,外侧线性 fade 到 MIN_OPACITY)。
   * 默认 120(±60°)。Fade out 而非 hide,让用户感知"更多卡在外"。
   */
  arcDegree: number;
  /** Container 旋转 + card opacity 的 CSS transition 毫秒数。默认 500。 */
  transitionDuration: number;
}

interface FanLayoutProps {
  characters: CharacterRow[];
  selectedCharId: number | null;
  onSelectCharacter: (id: number) => void;
  layoutParams?: Partial<FanLayoutParams>;
  /** 调试模式:显示圆心 + 每卡 index/angle 角标。默认 false。 */
  debug?: boolean;
}

// 弧外卡的最低 opacity(完全背面也保留 15% 让"还在那里"的提示存在)
const MIN_OPACITY = 0.15;
// CharacterCard browse 尺寸(与 CharacterCard.tsx SIZE_BROWSE 同步)。
// 不 import 是因为 CharacterCard 把它定义为 module-private const;数值化
// 重复一次比 export 更轻,数值漂移由 layout 视觉验收兜底。
const CARD_W = 160;
const CARD_H = 240;

/**
 * 最短路径 delta(支持非整数 N/2,即 N 为奇数也工作)。
 *
 *   delta = ((target - current + N/2) mod N) - N/2  ∈ [-N/2, N/2)
 *
 * JS ``%`` 对负数返负数,先 ``((x % N) + N) % N`` 兜成 [0, N)。
 */
function shortestDelta(target: number, current: number, n: number): number {
  if (n <= 1) return 0;
  const offset = target - current + n / 2;
  const mod = ((offset % n) + n) % n;
  return mod - n / 2;
}

/** 把 displayed angle 折回 [-180, 180],用于 fade 计算。 */
function normalizeAngle(deg: number): number {
  let a = deg % 360;
  if (a > 180) a -= 360;
  if (a < -180) a += 360;
  return a;
}

/** |displayed| ≤ arcDeg/2 → 1;否则线性降到 MIN_OPACITY。 */
function fadeOpacity(displayedDeg: number, arcDeg: number): number {
  const absD = Math.abs(normalizeAngle(displayedDeg));
  const half = arcDeg / 2;
  if (absD <= half) return 1;
  const range = 180 - half;
  if (range <= 0) return MIN_OPACITY;
  const t = (absD - half) / range;
  return Math.max(MIN_OPACITY, 1 - t * (1 - MIN_OPACITY));
}

/** value mod n → [0, n)(JS ``%`` 负数兜底)。 */
function posMod(value: number, n: number): number {
  return ((value % n) + n) % n;
}

export default function FanLayout({
  characters,
  selectedCharId,
  onSelectCharacter,
  layoutParams,
  debug = false,
}: FanLayoutProps) {
  // 视口 H 监听 resize → 默认 centerOffsetY 跟随
  const [viewportH, setViewportH] = useState(
    typeof window !== 'undefined' ? window.innerHeight : 800,
  );
  useEffect(() => {
    const onResize = () => setViewportH(window.innerHeight);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const params: FanLayoutParams = useMemo(
    () => ({
      radius:             layoutParams?.radius             ?? 600,
      centerOffsetY:      layoutParams?.centerOffsetY      ?? viewportH + 100,
      arcDegree:          layoutParams?.arcDegree          ?? 120,
      transitionDuration: layoutParams?.transitionDuration ?? 500,
    }),
    [layoutParams, viewportH],
  );

  const N = characters.length;
  const stepDeg = N > 0 ? 360 / N : 0;

  // -------------------------------------------------------------------------
  // currentIndex:**unbounded** 整数。允许 99→100→... 累积,这样 CSS transition
  // 自然产出"短路径转 +stepDeg"而非"长路径 vs 短路径需要 JS 算"。归一只在
  // 算 selected / fade 时用 ``posMod``。
  // -------------------------------------------------------------------------
  const [currentIndex, setCurrentIndex] = useState<number>(() => {
    if (selectedCharId == null || N === 0) return 0;
    const idx = characters.findIndex((c) => c.id === selectedCharId);
    return idx >= 0 ? idx : 0;
  });

  // selectedCharId 外部变化 → 最短路径 sync。
  // 用 ref 跟"是否首次 sync",首次 snap(避免初始 mount 时大转一圈)。
  const firstSyncRef = useRef(true);
  useEffect(() => {
    if (N === 0 || selectedCharId == null) return;
    const target = characters.findIndex((c) => c.id === selectedCharId);
    if (target < 0) return;
    setCurrentIndex((prev) => {
      const prevMod = posMod(prev, N);
      // prevMod 已经等于 target → 不变(避免 React StrictMode 双调用浪费 setState)
      if (prevMod === target) return prev;
      const delta = shortestDelta(target, prevMod, N);
      return prev + delta;
    });
    firstSyncRef.current = false;
  }, [selectedCharId, characters, N]);

  if (N === 0) return null;

  const currentMod = posMod(currentIndex, N);
  const containerRotate = -currentIndex * stepDeg;

  return (
    <div
      className="fixed inset-0 overflow-hidden pointer-events-none"
      // pointer-events: none 让 layout 容器透传;卡牌自己设 auto 收 click
    >
      {debug && (
        <div
          className="absolute pointer-events-none"
          style={{
            left:   '50%',
            top:    params.centerOffsetY,
            width:  10,
            height: 10,
            transform: 'translate(-50%, -50%)',
            background:   'red',
            borderRadius: '50%',
            zIndex: 100,
          }}
          title="circle center"
        />
      )}

      {/* axis:0×0 的旋转锚。所有卡 absolute 定位在 axis 局部坐标系内;
          axis rotate 后所有卡跟着转。transform-origin: 0 0(默认 50% 50%
          对 0×0 元素 NO-OP,但显式声明更清晰)。 */}
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
        {characters.map((c, i) => {
          const angle_i = i * stepDeg;
          const rad = (angle_i * Math.PI) / 180;
          const x = params.radius * Math.sin(rad);
          const y = -params.radius * Math.cos(rad);

          const displayed = (i - currentIndex) * stepDeg;
          const opacity = fadeOpacity(displayed, params.arcDegree);
          const isSelected = i === currentMod;

          // wrapper:仅做 absolute 定位,把卡的 bottom-center 锚在 (x, y)。
          // 不设 transform — 旋转交给 CharacterCard 自身,transform-origin
          // 才能正确生效在 bottom-center。
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
                // wrapper 也 willChange:opacity 持续变,避免 paint flicker
                willChange:    'opacity',
              }}
            >
              <CharacterCard
                character={c}
                variant="browse"
                rotation={angle_i}
                selected={isSelected}
                onClick={() => {
                  setCurrentIndex((prev) => {
                    const prevMod = posMod(prev, N);
                    if (prevMod === i) return prev;
                    const delta = shortestDelta(i, prevMod, N);
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
                  i={i} ang={angle_i.toFixed(0)}° disp={normalizeAngle(displayed).toFixed(0)}°
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
