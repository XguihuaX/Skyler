/**
 * bugfix-extra: 全屏 / 窗口切换 hook。
 *
 * Primary: Tauri v2 ``getCurrentWindow().setFullscreen / isFullscreen``。
 * Fallback: 浏览器 dev 跑(yarn dev 直接打开 localhost)时, Tauri API 不
 * 存在会抛 —— catch 后走 Web Fullscreen API(``document.fullscreenElement``
 * / ``requestFullscreen`` / ``exitFullscreen``)。
 *
 * 状态同步路径:
 *   - mount 时 ``isFullscreen()`` 拉初值
 *   - 监听 Tauri window ``onResized`` —— 用户用 macOS 绿色 traffic light /
 *     ``Cmd+Ctrl+F`` 系统快捷键进退全屏会触发 resize, 状态自动同步
 *   - Web fallback 路径监听 ``fullscreenchange`` 事件做同样的事
 *
 * 任一 API 都不可用(非 Tauri 且无 Web Fullscreen API)时 ``toggle`` 静默
 * noop, ``isFullscreen`` 恒 false —— 按钮可点但不响应, console.warn 一次。
 */
import { useCallback, useEffect, useState } from 'react';
import { getCurrentWindow } from '@tauri-apps/api/window';

export interface UseFullscreenResult {
  isFullscreen: boolean;
  toggle: () => Promise<void>;
}

export function useFullscreen(): UseFullscreenResult {
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    let mounted = true;
    let unlistenTauri: (() => void) | null = null;

    const syncFromTauri = async () => {
      try {
        const win = getCurrentWindow();
        const fs = await win.isFullscreen();
        if (mounted) setIsFullscreen(fs);
      } catch {
        // Tauri 不可用 —— 安静切到 Web API 同步
        if (mounted) {
          setIsFullscreen(Boolean(document.fullscreenElement));
        }
      }
    };

    const setupTauri = async () => {
      try {
        const win = getCurrentWindow();
        // Tauri ``onResized`` 在用户全屏 / 退出全屏 / 普通 resize 都会触发。
        // 全部 hop 一道 ``isFullscreen()`` 判断真状态。
        unlistenTauri = await win.onResized(() => {
          void syncFromTauri();
        });
      } catch {
        // dev 浏览器跑, Tauri 不存在 —— onResized 抛 import / runtime error
        // 都吞, 走 Web fallback。
      }
    };

    void syncFromTauri();
    void setupTauri();

    // Web API change 事件兜底(Tauri 环境冗余, 但 dev 浏览器必需)
    const onFsChange = () => {
      if (mounted) setIsFullscreen(Boolean(document.fullscreenElement));
    };
    document.addEventListener('fullscreenchange', onFsChange);

    return () => {
      mounted = false;
      if (unlistenTauri) unlistenTauri();
      document.removeEventListener('fullscreenchange', onFsChange);
    };
  }, []);

  const toggle = useCallback(async () => {
    // Try Tauri first
    try {
      const win = getCurrentWindow();
      const current = await win.isFullscreen();
      await win.setFullscreen(!current);
      setIsFullscreen(!current);
      return;
    } catch (e) {
      // 退到 Web API
      console.warn('[useFullscreen] Tauri setFullscreen 失败, 尝试 Web API:', e);
    }

    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
        setIsFullscreen(false);
      } else if (document.documentElement.requestFullscreen) {
        await document.documentElement.requestFullscreen();
        setIsFullscreen(true);
      } else {
        console.warn('[useFullscreen] 全屏 API 不可用');
      }
    } catch (e2) {
      console.warn('[useFullscreen] Web Fullscreen API 也失败:', e2);
    }
  }, []);

  return { isFullscreen, toggle };
}
