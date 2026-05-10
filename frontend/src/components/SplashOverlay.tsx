/**
 * v3.5 chunk 5b — 启动入场 splash video。
 *
 * 生命周期：
 *  1. mount：读 localStorage ``momoos.splashEnabled`` (default true)
 *  2. 关闭 → 立即 onFinished()
 *  3. fetch HEAD /splash/intro.mp4
 *     - 404 / fetch 抛错 → 立即 onFinished()（silent skip，控制台无 error）
 *     - 200 → 渲染 <video> 全屏
 *  4. 跳过条件（任一触发）：
 *     - video onEnded
 *     - 任意 click（覆盖层全屏 onClick）
 *     - 任意 keydown（document listener）
 *     - video onError
 *  5. 跳过后 CSS opacity 300ms → 0 → onFinished()
 *
 * z-index 9999 顶层。App.tsx 用 splashDone state 控主视图 fade-in。
 *
 * Tauri prod 兼容：fetch HEAD 在 Tauri webview 走 ``tauri.localhost`` 协议
 * 仍然 ok；万一 HEAD 在某 Tauri 配置下被拦截，<video onError> 会兜底立
 * 即 onFinished()。
 *
 * mp4 only：webm 不在 macOS Tauri webview 上稳定支持（spec splash/README.md）。
 */
import { useEffect, useRef, useState } from 'react';

const LS_SPLASH_ENABLED = 'momoos.splashEnabled';
const SPLASH_URL = '/splash/intro.mp4';
const FADE_MS = 300;

interface SplashOverlayProps {
  onFinished: () => void;
}

type LifecycleState =
  | 'probing'        // 初始：localStorage 检查 + fetch HEAD
  | 'playing'        // video 渲染中
  | 'fading'         // 触发 fade，等 transition end → onFinished
  | 'done';          // 已 onFinished，不再渲染

export default function SplashOverlay({ onFinished }: SplashOverlayProps) {
  const [phase, setPhase] = useState<LifecycleState>('probing');
  const videoRef = useRef<HTMLVideoElement | null>(null);
  // 用 ref 防 race：fade 计时器走完时 phase 可能已变成 done（来自其他 path），
  // 不允许重复触发 onFinished。
  const finishedRef = useRef(false);

  const finish = () => {
    if (finishedRef.current) return;
    finishedRef.current = true;
    setPhase('done');
    onFinished();
  };

  const beginFade = () => {
    if (finishedRef.current) return;
    setPhase('fading');
    // CSS transition ends 后 finish；不依赖 onTransitionEnd（react 多次触发时
    // 不稳），用 setTimeout 兜底。
    window.setTimeout(finish, FADE_MS);
  };

  // ── 1. mount：localStorage 检查 + HEAD probe ─────────────────────────
  useEffect(() => {
    let cancelled = false;

    // 1a. 关掉 toggle → 立即 onFinished
    try {
      const v = localStorage.getItem(LS_SPLASH_ENABLED);
      if (v === 'false') {
        finish();
        return;
      }
    } catch {
      // localStorage 不可用时按默认 ON 处理（往下走 HEAD probe）
    }

    // 1b. HEAD 检测文件存在
    (async () => {
      try {
        const res = await fetch(SPLASH_URL, { method: 'HEAD' });
        if (cancelled) return;
        if (!res.ok) {
          // 404 / 其他非 2xx → 文件不存在，silent skip
          finish();
          return;
        }
        // 文件存在，进入播放阶段
        setPhase('playing');
      } catch {
        // network error / Tauri 协议限制 / 离线 → silent skip
        if (!cancelled) finish();
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── 2. 全局键盘跳过 ────────────────────────────────────────────────
  useEffect(() => {
    if (phase !== 'playing') return;
    const onKey = (_e: KeyboardEvent) => {
      beginFade();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  // probing / done → 不渲染（probing 一般微秒级，HEAD 200 → playing；不阻塞首屏）
  if (phase === 'probing' || phase === 'done') {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-[10000]"
      style={{
        background: 'black',
        opacity: phase === 'fading' ? 0 : 1,
        transition: `opacity ${FADE_MS}ms ease-out`,
        pointerEvents: phase === 'fading' ? 'none' : 'auto',
      }}
      onClick={beginFade}
    >
      <video
        ref={videoRef}
        src={SPLASH_URL}
        autoPlay
        muted
        playsInline
        // 不 loop —— splash 一次性
        onEnded={beginFade}
        onError={beginFade}
        className="w-full h-full"
        style={{ objectFit: 'cover' }}
      />
      <div
        className="absolute bottom-6 right-6 text-xs select-none"
        style={{ color: 'rgba(255,255,255,0.5)' }}
      >
        点击 / 按键跳过
      </div>
    </div>
  );
}
