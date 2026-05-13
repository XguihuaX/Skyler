/**
 * v4-fan chunk 2 — 🔥 P0 spike: backdrop-blur 性能验证。
 *
 * docs/fan-ui-starting-context.md §9 P0 列了"多卡同时 transform + 父层
 * backdrop-filter blur(20px) 在 Tauri WKWebView 上可能掉到 30fps 以下"。
 * 本 spike 渲染 8 张 CharacterCard + 一个全屏 backdrop-blur overlay 的
 * toggle,实时显示 fps,让用户在真机上验证。
 *
 * ⚠️ CC 不能跑 Tauri 真机;**用户必须自己跑** dev 环境验证 fps。
 *
 * ── 启用方式 ──────────────────────────────────────────────────────────────
 * 1. ``cd frontend && npm run dev``(本机)或 ``yarn tauri dev``(真机)
 * 2. 浏览器/Tauri 窗口里打开:``http://localhost:5173/?spike=blur``
 * 3. 等 8 张卡渲染出来(走 placeholder.png,不需要后端)
 * 4. 看左上角 fps 计数。先看 baseline(blur OFF),再点按钮 toggle ON。
 *
 * ── 验收阈值 ──────────────────────────────────────────────────────────────
 * - **绿(≥55fps)**:走 §6 推荐方案(全屏 backdrop-blur overlay + 8 卡)
 * - **黄(30-55fps)**:可接受,但 ship 前再 polish 一轮(降 blur 半径
 *   / 减卡数)
 * - **红(<30fps)**:走 audit §9 P0 列的退化方案(下面 [DEGRADATION] 段)
 *
 * ── [DEGRADATION] 三个退化方案 ────────────────────────────────────────────
 * A. **filter: blur() 替代 backdrop-filter**
 *    - 把背景层做成 ``<img filter:blur(8px)>`` 而非 overlay 用 backdrop。
 *    - 优势:filter 走光栅化 cache,backdrop 每帧重算。WKWebView 上
 *      filter 通常便宜 2-3x。
 *    - 代价:背景必须是静态图(不能跟 Live2D 联动);Fan UI overlay 期间
 *      Live2D 不渲染(本来就是),所以 OK。
 *
 * B. **detail 态只 blur 一帧 snapshot**
 *    - browse 态完全不 blur;进 detail 时 ``html2canvas`` 截当前帧 →
 *      blur(8px) 一次性 paint。
 *    - 优势:零持续成本。
 *    - 代价:html2canvas 拉一个 ~30KB 依赖,违反 audit §3 依赖红线;且
 *      Live2D canvas 不能被 html2canvas 截到(WebGL context isolation),
 *      只能截 DOM。
 *
 * C. **减少同屏卡数到 5 张**
 *    - layout 算法只渲染 5 张可见 + 2 张离屏 buffer(virtualized fan)。
 *    - 优势:零功能损失,仅减视觉密度。5 张实际比 8 张更舒适(扇面太
 *      密反而难选)。
 *    - 代价:需要"翻页"或"滚动"到边缘 6/7/8 号角色,UX 复杂度上升。
 *
 * 推荐顺序:**A → C → B**(A 最便宜;C 改 layout;B 引依赖最重)。
 *
 * ── spike commit 后清理 ──────────────────────────────────────────────────
 * 本文件路径含 ``__spike__/`` 前缀,Fan-3 commit 时一并 ``git rm -r``。
 * 不进 production bundle 的契约靠 lazy import + ?spike=blur query 守住:
 * 没人开启那个 query → tree-shake 不到本文件。
 */
import { useEffect, useRef, useState } from 'react';
import CharacterCard from '../CharacterCard';
import type { CharacterRow } from '../../../lib/config';

// 8 个假 character。splash_art_url 全 null → 全走 placeholder,不依赖
// 后端。id 唯一即可,key 用 React 默认 index 也行,这里给真 id 显式。
const FAKE_CHARS: CharacterRow[] = Array.from({ length: 8 }, (_, i) => ({
  id: 9000 + i,
  name: `Spike#${i + 1}`,
  persona: '',
  avatar_path:       null,
  voice_model:       null,
  live2d_model:      null,
  emotion_map_json:  null,
  motion_map_json:   null,
  hit_area_map_json: null,
  background_path:   null,
  splash_art_url:    null,
  created_at:        null,
}));

// 弧形布局参数:8 张卡均匀铺在 ±32° 弧上,半径 320px。
// 与 Fan-3 真布局算法**等价**(只是参数固定,Fan-3 会做 responsive)。
const ARC_DEG_HALF = 32;
const ARC_RADIUS  = 320;

function fanGeometry(index: number, count: number) {
  // -ARC_DEG_HALF .. +ARC_DEG_HALF,等距分配。count=1 时居中。
  const t = count > 1 ? index / (count - 1) : 0.5;
  const angle = -ARC_DEG_HALF + t * 2 * ARC_DEG_HALF;
  const rad = (angle * Math.PI) / 180;
  // 弧上位置:笛卡尔。圆心在屏幕下方 (0, ARC_RADIUS),向上凸。
  const x = Math.sin(rad) * ARC_RADIUS;
  const y = -Math.cos(rad) * ARC_RADIUS + ARC_RADIUS * 0.4; // 抬高视觉中心
  return { x, y, angle };
}

export default function BlurSpike() {
  const [blurOn, setBlurOn] = useState(false);
  const [fps, setFps] = useState(0);
  const [selectedIdx, setSelectedIdx] = useState(3);

  // -------------------------------------------------------------------------
  // FPS 监控:requestAnimationFrame 边沿计数,每秒刷一次显示。
  // 这种 RAF-tick 计数法在 Chrome / Safari / WKWebView 上等效——浏览器把
  // RAF callback 跟 vsync 对齐,频率即帧率。掉帧时连续两帧间隔 > 16.7ms,
  // 计数自然降。
  // -------------------------------------------------------------------------
  const frameCountRef = useRef(0);
  const lastSampleRef = useRef(performance.now());
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const tick = () => {
      frameCountRef.current += 1;
      const now = performance.now();
      const elapsed = now - lastSampleRef.current;
      if (elapsed >= 1000) {
        const fpsNow = Math.round((frameCountRef.current * 1000) / elapsed);
        setFps(fpsNow);
        frameCountRef.current = 0;
        lastSampleRef.current = now;
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  const fpsColor =
    fps >= 55 ? '#4ade80'    // green
    : fps >= 30 ? '#facc15'  // yellow
    : '#f87171';             // red

  return (
    <div
      className="fixed inset-0 overflow-hidden"
      style={{
        background:
          'radial-gradient(circle at 50% 60%, #2a2045 0%, #16102a 70%, #0a0815 100%)',
      }}
    >
      {/* ──────────────────────────────────────────────────────────────────
          背景层(toggle 目标):全屏 backdrop-blur(8px) + brightness(0.5)。
          backdrop-filter 是 P0 性能风险点 —— overlay 一开,WKWebView 每帧
          要把背后所有 layer 重新 raster + blur。8 张卡 + 这个 overlay
          就是 audit §9 列的最坏场景。

          注意:这个 div 必须在卡片之**前**渲染(z-index 也低),让 backdrop
          有"背后内容"可模糊。否则 backdrop-filter no-op。
          ────────────────────────────────────────────────────────────────── */}
      {blurOn && (
        <div
          className="absolute inset-0"
          style={{
            backdropFilter: 'blur(8px) brightness(0.5)',
            WebkitBackdropFilter: 'blur(8px) brightness(0.5)',
            zIndex: 5,
          }}
        />
      )}

      {/* ──────────────────────────────────────────────────────────────────
          8 张 fan layout 卡牌。坐标用 absolute + 屏幕中心锚定。
          ────────────────────────────────────────────────────────────────── */}
      <div
        className="absolute"
        style={{
          left: '50%',
          top:  '55%',
          zIndex: 10,
        }}
      >
        {FAKE_CHARS.map((c, i) => {
          const g = fanGeometry(i, FAKE_CHARS.length);
          return (
            <div
              key={c.id}
              className="absolute"
              style={{
                left: -80,   // 卡宽 160 的一半,让 transform 中心是卡心
                top:  -120,  // 卡高 240 的一半
              }}
            >
              <CharacterCard
                character={c}
                variant="browse"
                rotation={g.angle}
                position={{ x: g.x, y: g.y, scale: 1 }}
                selected={i === selectedIdx}
                onClick={() => setSelectedIdx(i)}
              />
            </div>
          );
        })}
      </div>

      {/* ──────────────────────────────────────────────────────────────────
          Toggle 按钮 + FPS HUD。fixed,zIndex 99 永远在最上层。
          ────────────────────────────────────────────────────────────────── */}
      <div
        className="fixed top-4 left-4 flex flex-col gap-2 font-mono text-sm"
        style={{ zIndex: 99 }}
      >
        <div
          className="rounded-md px-3 py-2"
          style={{
            background: 'rgba(0, 0, 0, 0.7)',
            color: fpsColor,
            border: `2px solid ${fpsColor}`,
            minWidth: 120,
          }}
        >
          <div style={{ fontSize: 24, fontWeight: 700, lineHeight: 1 }}>
            {fps} fps
          </div>
          <div style={{ fontSize: 10, opacity: 0.7, marginTop: 4 }}>
            target ≥ 55fps
          </div>
        </div>

        <button
          type="button"
          onClick={() => setBlurOn((v) => !v)}
          className="rounded-md px-3 py-2 transition"
          style={{
            background: blurOn ? '#dc2626' : '#16a34a',
            color: '#fff',
            fontWeight: 600,
            border: 'none',
            cursor: 'pointer',
          }}
        >
          backdrop-blur: {blurOn ? 'ON (toggle off)' : 'OFF (toggle on)'}
        </button>

        <div
          className="rounded-md px-3 py-2 text-xs"
          style={{
            background: 'rgba(0, 0, 0, 0.6)',
            color: '#aaa',
            maxWidth: 280,
            lineHeight: 1.4,
          }}
        >
          P0 spike:对比 blur on/off 的 fps。
          <br />
          ≥55=绿(走 overlay 方案),30-55=黄(polish),
          {'<'}30=红(走退化方案 A/B/C,见文件注释)。
        </div>
      </div>
    </div>
  );
}
