import { getCurrentWindow } from '@tauri-apps/api/window';
import { invoke } from '@tauri-apps/api/core';

/**
 * 设置当前窗口是否忽略鼠标事件（鼠标穿透）。
 * - true：鼠标点击穿过窗口，操作下层应用/桌面
 * - false：窗口正常响应鼠标
 *
 * macOS 行为：透明区域和不透明区域都会受此 flag 影响，
 * 模块 3 Widget 模式会在控件 hover 时动态切换。
 */
export async function setClickThrough(ignore: boolean): Promise<void> {
  const win = getCurrentWindow();
  await win.setIgnoreCursorEvents(ignore);
}

/**
 * 根据 mode 调整窗口尺寸、位置和置顶属性。
 * - widget: 350×500，居中，置顶
 * - panel:  1100×750，居中，不置顶
 * 不修改 tauri.conf.json，运行时通过 JS API 切换。
 */
export async function applyModeWindowProps(mode: 'widget' | 'panel'): Promise<void> {
  const { LogicalSize } = await import('@tauri-apps/api/dpi');
  const win = getCurrentWindow();
  if (mode === 'panel') {
    await win.setSize(new LogicalSize(1100, 750));
    await win.center();
    await win.setAlwaysOnTop(false);
  } else {
    await win.setSize(new LogicalSize(350, 500));
    await win.center();
    await win.setAlwaysOnTop(true);
  }
}

const BACKEND_BASE = 'http://127.0.0.1:8000';

/**
 * 写 config.yaml 一个字段并通知后端重新加载。
 * key_path 形如 "tts.enabled"，按点分层级。
 * Tauri 写文件失败或后端 reload 非 2xx 都会 throw `Error`。
 *
 * hotfix-7: Tauri ``invoke`` 在 Rust 端 ``Result<(), String>`` 返 Err 时
 * 直接以**字符串**形式 reject Promise (不是 Error 对象)。前端 catch
 * ``e.message`` 取出 ``undefined`` 弹 toast 写"启用 TTS 写入失败：undefined"
 * 看不出原因。本函数统一把所有 reject 路径都 normalize 成 ``Error``：
 *   - invoke 失败 (Rust Err 字符串) → ``new Error(<rust msg>)``
 *   - fetch /api/config/reload 失败 → ``new Error('config reload failed: <status>: <body>')``
 * 调用方 ``.catch((e: Error) => e.message)`` 永远拿到有用信息。
 */
export async function setConfigField(keyPath: string, value: unknown): Promise<void> {
  try {
    await invoke('write_config_field', { keyPath, value });
  } catch (e) {
    // Tauri Rust ``Err(String)`` → reject 一个 plain string。``e instanceof Error``
    // 是 false 时 (e as Error).message === undefined。这里强转 string。
    let msg: string;
    if (typeof e === 'string') {
      msg = e;
    } else if (e instanceof Error) {
      msg = e.message;
    } else {
      // 未知 shape (number / null / object) → JSON 兜底
      try { msg = JSON.stringify(e); } catch { msg = String(e); }
    }
    throw new Error(`write_config_field('${keyPath}') failed: ${msg}`);
  }
  const r = await fetch(`${BACKEND_BASE}/api/config/reload`, { method: 'POST' });
  if (!r.ok) {
    // 把 status + body 都带上让 toast 显示具体原因
    let bodyHint = '';
    try {
      const text = await r.text();
      if (text) bodyHint = ` — ${text.slice(0, 120)}`;
    } catch { /* ignore */ }
    throw new Error(`config reload failed: HTTP ${r.status}${bodyHint}`);
  }
}

export { fetchConfig } from './config';
export type { AppConfig } from './config';
