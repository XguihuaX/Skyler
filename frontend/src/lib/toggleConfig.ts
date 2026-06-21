// Two-input 单一逻辑入口 · 防 SettingsPanel + ChatInput 两入口逻辑漂。
//
// 用法:
//   const setEnableThinking = useAppStore((s) => s.setEnableThinking);
//   await toggleConfigField(setEnableThinking, 'thinking.enable_thinking',
//     !enableThinking, (e) => console.error('thinking sync failed', e));
//
// 行为:
//   1. 乐观 setter(next) — UI 即时反应
//   2. setConfigField(keyPath, next) — 持久化 yaml(/api/config POST)
//   3. 失败回滚 setter(!next) + onError(可选)— 同 SettingsPanelLegacy
//      remoteToggle 的 catch 链路语义

import { setConfigField } from './window';

export async function toggleConfigField(
  setter: (v: boolean) => void,
  keyPath: string,
  next: boolean,
  onError?: (e: unknown) => void,
): Promise<void> {
  setter(next);
  try {
    await setConfigField(keyPath, next);
  } catch (e) {
    setter(!next);
    onError?.(e);
  }
}
