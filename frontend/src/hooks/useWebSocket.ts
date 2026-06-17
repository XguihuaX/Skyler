import { useEffect, useRef, useCallback } from 'react';
import { useAppStore } from '../store';
import { pipeAudioElement } from '../lib/ttsAudio';

const WS_URL = 'ws://127.0.0.1:8000/ws';
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;

function newClientId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

interface WsMessage {
  type: string;
  content?: string;
  message?: string;
  todo_id?: number;
  message_id?: number | null;
  // v3-F: thinking 消息携带的内心独白文本
  value?: string;
  // v3-F #4: done 消息可能带 interrupted=true 表示这一轮被打断
  interrupted?: boolean;
  // v3-G chunk 2：proactive engine 触发的轮，所有该轮的 chunk 都带这两个字段。
  // 老前端忽略未知字段照常工作；新前端按 trigger 名映射 toast label + 给气泡
  // 打 kind='proactive' 标。
  proactive?: boolean;
  proactive_trigger?: string;
  // v3-G chunk 3b: state_update 消息字段
  character_id?: number;
  mood?: string;
  intimacy?: number;
  thought?: string | null;
  activity?: string | null;
  // Bug 2 修法:backend 在聊天 UI 类型 chunks 上附 conv_id;前端按
  // currentConversationId filter,stale chunks 丢弃。
  conversation_id?: number | null;
  // INV-9 §7:'tts_cost_cap_exceeded' 事件字段(Fish daily/monthly cost cap)
  reason?: 'daily' | 'monthly';
  today_cost?: number;
  month_cost?: number;
  daily_cap?: number;
  monthly_cap?: number;
}

// v3-G chunk 2 / 2.6 / 4: trigger.name -> toast 标题。后续加 trigger 时只在这里 append。
const PROACTIVE_TOAST_LABEL: Record<string, string> = {
  morning_briefing: '🌅 早安简报',
  wake_call: '🌅 早安',
  lunch_call: '🍱 午饭时间',
  dinner_call: '🍽 晚饭时间',
  bedtime_chat: '🌙 睡前问候',
  long_idle: '💭 想你一下',
};

interface UseWebSocketReturn {
  sendText: (content: string) => void;
  sendVoice: (audioBase64: string) => void;
  // v3-F #4：通知后端取消当前 LLM stream + TTS playback
  sendInterrupt: () => void;
  // v3-E1 step3：用户点 Live2D canvas，触发后端主动对话
  sendTouch: () => void;
  // Rule B(绑定语义)— 切角色时把新 (char, conv) 推给 backend。
  sendCharacterSwitch: (
    characterId: number, conversationId: number | null,
  ) => void;
  // 2026-06-15 ⑤ · MCP tool 调用前确认 modal 回应
  sendMcpToolConfirmResponse: (requestId: string, accept: boolean) => void;
  isConnected: () => boolean;
}

export function useWebSocket(): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const audioQueueRef = useRef<HTMLAudioElement[]>([]);
  const isPlayingRef = useRef(false);
  // v3-E1 step4 修（方案 B）：当前播放段的"超时兜底"timer 句柄。
  // createMediaElementSource 把 audio element 接进 WebAudio 图后，'ended' /
  // 'pause' / 'loadedmetadata' 事件都可能不打，靠 wall-clock setTimeout 兜底
  // 推进队列。每段最多一个 timer，handleEnd 触发或 turn 收尾要 clear，避免
  // 迟到的 timeout 误触发 playNextAudio。
  const playbackTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 诊断：当前 turn 内已收到的 text_chunk 计数（done 时重置）
  const textChunkCountRef = useRef(0);

  // 持有 store 模块引用，不订阅，避免重渲染
  const store = useAppStore;

  const playNextAudio = useCallback(() => {
    if (isPlayingRef.current) return;
    const next = audioQueueRef.current.shift();
    if (!next) {
      isPlayingRef.current = false;
      // 队列播完，状态回 idle
      const { status, muteWhileSpeaking, setStatus, setMicMuted } = store.getState();
      if (status === 'speaking') {
        setStatus('idle');
        if (muteWhileSpeaking) setMicMuted(false);
      }
      return;
    }
    isPlayingRef.current = true;

    // v3-E1 step4 修（方案 B）：createMediaElementSource 把 audio element
    // 接进 WebAudio 图后，'ended' 事件触发不可靠（方案 A 已实测失败：第二
    // 段以后 onended 不打；pause 守卫的 duration 也常 NaN，guard 永 false）。
    // 改用三层兜底：
    //   1. 'ended' 事件（少数情况下还能打就用）
    //   2. 'error' 事件（解码 / 播放失败时也接力，避免一段崩了整队列卡死）
    //   3. wall-clock setTimeout（不依赖元素事件）—— 主要靠这个推进
    //      - loadedmetadata 拿到 duration → setTimeout(duration*1000 + 1000)
    //      - duration 不可信（NaN / Infinity / loadedmetadata 不打）→ 30s 极端兜底
    // handleEnd 用 endedHandled flag 幂等，多路径触发只推进一次。
    let endedHandled = false;
    const clearPlaybackTimer = () => {
      if (playbackTimeoutRef.current !== null) {
        clearTimeout(playbackTimeoutRef.current);
        playbackTimeoutRef.current = null;
      }
    };
    const handleEnd = () => {
      if (endedHandled) return;
      endedHandled = true;
      clearPlaybackTimer();
      isPlayingRef.current = false;
      playNextAudio();
    };

    next.addEventListener('ended', handleEnd);
    next.addEventListener('error', handleEnd);

    // loadedmetadata 拿到 duration 后，把"30s 极端兜底"换成精确兜底。
    // 极端情况下 loadedmetadata 都不打（比如 createMediaElementSource 把
    // 这个事件也劫持了），就保留 30s 兜底，最差 30s 后队列也能往前走。
    next.addEventListener('loadedmetadata', () => {
      if (endedHandled) return;
      clearPlaybackTimer();
      if (!isFinite(next.duration) || next.duration <= 0) {
        playbackTimeoutRef.current = setTimeout(handleEnd, 30_000);
        return;
      }
      const safeMs = Math.ceil(next.duration * 1000) + 1000;
      playbackTimeoutRef.current = setTimeout(handleEnd, safeMs);
    });

    // 极端兜底先装上，loadedmetadata 触发后会被换成精确版本
    playbackTimeoutRef.current = setTimeout(handleEnd, 30_000);

    next.play().catch(handleEnd);
  }, [store]);

  const handleMessage = useCallback((msg: WsMessage) => {
    const s = store.getState();

    // Bug 2 修法(audit_lost_replies.md):chunks 自带 ``conversation_id``
    // metadata 时,与当前 UI 上 ``currentConversationId`` 不匹配则视为
    // **stale chunk**(in-flight turn 用户已切走),丢弃不影响 UI。
    // Backend 仍按 9039d75 snapshot 把 reply 写进原 conv 的 chat_history;
    // 用户切回原 conv → ConversationList click → fetchMessages 重新加载
    // → 看到 reply,Rule A "不丢" 兑现。
    //
    // 只过滤聊天 UI / TTS 播放相关的类型:text_chunk / audio_chunk /
    // thinking / done / asr_result。
    // 不过滤 emotion / motion / state_update —— 那些是 character-level 状态,
    // 跨 conv 适用(同一 char 切不同 conv 仍应反映该 char 当前心情/动作)。
    const FILTERABLE_TYPES = new Set([
      'asr_result', 'text_chunk', 'audio_chunk', 'thinking', 'done',
    ]);
    if (FILTERABLE_TYPES.has(msg.type) && msg.conversation_id !== undefined) {
      const cur = s.currentConversationId;
      if (msg.conversation_id !== cur) {
        console.log(
          `[FRONT] drop stale ${msg.type} from conv=${msg.conversation_id} `
          + `(currentConv=${cur})`,
        );
        return;
      }
    }

    switch (msg.type) {
      case 'asr_result': {
        const content = msg.content ?? '';
        if (content) s.setAsrText(content);
        if (msg.message_id != null && content) {
          s.appendChatMessage({
            id: `asr-${msg.message_id}`,
            role: 'user',
            content,
            streaming: false,
            ts: performance.now(),
            // ASR 永远是用户主动语音输入，不是 touch / proactive
            kind: 'normal',
          });
        }
        break;
      }

      case 'text_chunk': {
        if (s.status !== 'speaking' && s.status !== 'thinking') {
          s.setStatus('thinking');
        }
        const chunk = msg.content ?? '';
        // 诊断 timer：相对 lastSendTimestamp 算 elapsed
        const t0 = s.lastSendTimestamp;
        const elapsed = t0 > 0 ? performance.now() - t0 : 0;
        const bytes = new Blob([chunk]).size;
        textChunkCountRef.current += 1;
        if (textChunkCountRef.current === 1) {
          console.log(`[FRONT] first text_chunk at ${elapsed.toFixed(0)}ms bytes=${bytes}`);
        } else {
          console.log(
            `[FRONT] text_chunk #${textChunkCountRef.current} at ${elapsed.toFixed(0)}ms bytes=${bytes}`,
          );
        }

        // v3-G chunk 2: proactive 轮第一个 chunk 弹 toast。判断"第一个 chunk"
        // 用 streamingMessageId === null（更可靠，覆盖 textChunkCountRef 在
        // 跨轮残留的边界）。trigger.name 映射不到 → 通用兜底文案。
        const isFirstProactiveChunk = msg.proactive && s.streamingMessageId === null;

        // 流式更新 chatMessages：第一个 chunk 创建 streaming assistant 气泡，
        // 后续 chunk 仅追加该气泡的 content（避免每 chunk 重建整 array）。
        if (s.streamingMessageId === null) {
          const id = newClientId('a');
          s.appendChatMessage({
            id,
            role: 'assistant',
            content: chunk,
            streaming: true,
            ts: performance.now(),
            // v3-G chunk 2: 后端 proactive=true 的 chunk → 流式气泡 kind='proactive'，
            // ChatHistory 渲染时加 "🌅（早安简报）" 灰字前缀；'touch' 不会经
            // text_chunk 出现（[touch] 行只是 user 占位，没有 assistant 流），
            // 所以 streaming 气泡只可能 'normal' / 'proactive'。
            kind: msg.proactive ? 'proactive' : 'normal',
            proactiveTrigger: msg.proactive ? msg.proactive_trigger : undefined,
          });
          s.setStreamingMessageId(id);
        } else {
          s.appendChatMessageContent(s.streamingMessageId, chunk);
        }

        if (isFirstProactiveChunk) {
          const trigName = msg.proactive_trigger ?? '';
          const label = PROACTIVE_TOAST_LABEL[trigName] ?? '✨ Momo 主动来了';
          s.pushNotification({ type: 'notify', content: label });
        }
        break;
      }

      case 'audio_chunk': {
        // 双保险：后端关闭 TTS 时不会推 audio_chunk，但万一推过来也丢弃
        if (!s.ttsEnabled) break;
        if (msg.content) {
          const audio = new Audio(`data:audio/wav;base64,${msg.content}`);
          // v3-E1 step4：把 audio 元素接进 TTS AudioContext 分析图，
          // 让 Live2DCanvas 的口型同步能取到振幅。createMediaElementSource
          // 会劫持元素输出，pipeAudioElement 内部已 connect 到 destination
          // 保证仍能听见。每个 audio 元素都是新 new 出来的，pipe 一次安全。
          pipeAudioElement(audio);
          audioQueueRef.current.push(audio);
          if (s.status !== 'speaking') {
            s.setStatus('speaking');
            if (s.muteWhileSpeaking) s.setMicMuted(true);
          }
          playNextAudio();
        }
        break;
      }

      case 'done': {
        const t0 = s.lastSendTimestamp;
        const elapsed = t0 > 0 ? performance.now() - t0 : 0;
        const interruptedFlag = msg.interrupted === true;
        console.log(
          `[FRONT] done at ${elapsed.toFixed(0)}ms total_text_chunks=${textChunkCountRef.current} interrupted=${interruptedFlag}`,
        );
        textChunkCountRef.current = 0;

        // 流式 assistant 气泡收尾（与 audio 无关，无条件）
        if (s.streamingMessageId !== null) {
          s.finishChatMessage(s.streamingMessageId);
          s.setStreamingMessageId(null);
        }

        // v3-E1 step4 修：以前 audioQueueRef.current = [] / clearTimeout /
        // setMicMuted(false) 是无条件执行的，导致 v3-F #3 并发 TTS 把 3 段
        // audio_chunk 在很短时间内推到 frontend、A1 还在播时 done 跟着到达 →
        // 队列被清空 → A2/A3 蒸发。修法：只有打断收尾才走"立即停"语义；正常
        // 完成留给 playNextAudio 链自然把 queue 排空，期间 mic 由 playNextAudio
        // 的 idle 分支兜底解除静音。
        if (interruptedFlag) {
          // 打断收尾：立即停队列 + 撤 timeout，立即解除 mic 静音
          audioQueueRef.current = [];
          if (playbackTimeoutRef.current !== null) {
            clearTimeout(playbackTimeoutRef.current);
            playbackTimeoutRef.current = null;
          }
          if (s.muteWhileSpeaking && s.micMuted) s.setMicMuted(false);
          // 标 'interrupted' 视觉，1.5s 后回 idle（保留视觉反馈给用户）
          s.setStatus('interrupted');
          window.setTimeout(() => {
            const cur = useAppStore.getState().status;
            // 若期间用户又开了新一轮，不要把它从 thinking 拽回 idle
            if (cur === 'interrupted') useAppStore.getState().setStatus('idle');
          }, 1500);
        } else if (s.status === 'thinking') {
          // 纯文字回复（无 audio_chunk）会卡 thinking，这里兜底直接回 idle
          // 有 audio_chunk 的情况下 status 是 'speaking'，由 playNextAudio
          // 在队列排空时切回 idle + 还原 mic，done case 不要插手。
          s.setStatus('idle');
        }
        break;
      }

      case 'error':
        console.error('[WS] backend error:', msg.message);
        s.setStatus('idle');
        // 删掉这一轮还没收完的 streaming 气泡
        if (s.streamingMessageId !== null) {
          s.removeChatMessage(s.streamingMessageId);
          s.setStreamingMessageId(null);
        }
        break;

      case 'tts_cost_cap_exceeded': {
        // INV-9 §7 · Fish daily / monthly cost cap 触达 → backend 已
        // fallback CosyVoice yaml default · 前端 toast 提示用户
        const reason = msg.reason as 'daily' | 'monthly' | undefined;
        const todayCost = typeof msg.today_cost === 'number' ? msg.today_cost : 0;
        const dailyCap = typeof msg.daily_cap === 'number' ? msg.daily_cap : 1;
        const monthCost = typeof msg.month_cost === 'number' ? msg.month_cost : 0;
        const monthlyCap = typeof msg.monthly_cap === 'number' ? msg.monthly_cap : 20;
        const content = reason === 'monthly'
          ? `本月 Fish 配额已用 $${monthCost.toFixed(3)} / $${monthlyCap}，本轮切回 CosyVoice`
          : `今日 Fish 配额已用 $${todayCost.toFixed(3)} / $${dailyCap}，本轮切回 CosyVoice`;
        console.warn('[WS] tts_cost_cap_exceeded:', { reason, todayCost, monthCost });
        s.pushNotification({ type: 'notify', content });
        break;
      }

      case 'thinking': {
        // v3-F：AI 内心独白，每轮最多一次。UI 显示在 StatusBadge 旁
        const value = msg.value ?? '';
        if (value) s.setCurrentThinking(value);
        break;
      }

      case 'emotion': {
        // v3-E1 step5：AI 当轮情感，每轮最多一次。透传 LLM 原始字符串。
        // Live2DCanvas useEffect 订阅 currentEmotion → 后续 v3-E2 接入视觉绑定。
        const value = msg.value ?? '';
        if (value) s.setCurrentEmotion(value);
        break;
      }

      case 'motion': {
        // v3-E1 step6：AI 当段动作，每段可命中一次（per-segment，不是 per-turn）。
        // 透传 LLM 输出的中文动作名（具体可用词以 frontend/src/config/live2d.ts
        // 的 motionMap 为准，例：放松 / 害羞 / 加油 / 撒娇）。
        // Live2DCanvas useEffect 订阅 currentMotion → motionMap 查 group/index
        // 调 model.motion(group, index, NORMAL)。同名动作连续命中只会触发一次
        // useEffect（依赖项引用相等），实测上够用 —— LLM 多段动作通常会换名字。
        const value = msg.value ?? '';
        if (value) s.setCurrentMotion(value);
        break;
      }

      case 'state_update': {
        // v3-G chunk 3b: 后端 <state_update> 标签解析后 push，或 reset_state
        // 路由 push (character.set_activity capability 2026-05-21 退役,改走
        // tag 唯一路径,详 INV-6 §1)。把 store currentCharacterState
        // 替换/合并；CharacterStatePanel 自动重渲染。
        const charId = msg.character_id ?? s.currentCharacterId ?? null;
        if (charId == null) break;
        const prev = s.currentCharacterState;
        s.setCurrentCharacterState({
          character_id: charId,
          mood: (msg.mood ?? prev?.mood ?? 'neutral') as
            | 'happy' | 'sad' | 'curious' | 'calm' | 'excited' | 'tired' | 'neutral',
          intimacy: msg.intimacy ?? prev?.intimacy ?? 0,
          thought: msg.thought !== undefined ? msg.thought : (prev?.thought ?? null),
          activity: msg.activity !== undefined ? msg.activity : (prev?.activity ?? null),
          last_interaction_at: prev?.last_interaction_at ?? null,
          updated_at: new Date().toISOString(),
        });
        break;
      }

      case 'notify':
        s.pushNotification({ type: 'notify', content: msg.content ?? '' });
        break;

      case 'alarm':
        s.pushNotification({ type: 'alarm', content: msg.content ?? '', todoId: msg.todo_id });
        break;

      // v3.5 chunk 8a — 后端 startup 自检发现 AppleScript 权限未授予时 push
      // 一条这个，让 ActivityPermissionModal 弹出来。
      case 'activity_permission_missing':
        s.setActivityPermissionHint((msg as { hint?: string }).hint ?? null);
        break;

      // UX-004: LLM 调 tool 之前 backend emit。tool_name 走 toolLoadingLabel
      // 前缀 mapping 由 UI 自己渲染(useWebSocket 不耦合 label 显示规则)。
      case 'tool_use_start': {
        const name = (msg as { tool_name?: string }).tool_name ?? null;
        if (name) s.setCurrentToolName(name);
        break;
      }

      // UX-004: tool 返回时 backend emit,带 duration_ms。前端清空 loading
      // (LLM 后续二次 LLM call 接续 text_chunk 流)。duration_ms 当前未消
      // 费,留给未来 "Momo 这个工具好慢哦" feedback UI 用(字段语义保留)。
      case 'tool_use_done':
        s.setCurrentToolName(null);
        break;

      // 2026-06-15 ⑤ · MCP tool 调用前确认请求 · backend 给 dangerous tool
      // 调用 wrap · 推这条 · 前端 MCPConfirmModal 接 store.mcpConfirmRequest
      // 弹窗 · 用户 accept/reject 后回 mcp_tool_confirm_response 帧。
      case 'mcp_tool_confirm_request': {
        const m = msg as {
          request_id?: string;
          cap_name?: string;
          server_name?: string;
          tool_name?: string;
          args_preview?: string;
        };
        if (m.request_id && m.cap_name && m.server_name && m.tool_name) {
          // 2026-06-15 batch 2 [confirm 边界] · 入队 · 不覆盖前一条
          s.enqueueMcpConfirm({
            request_id: m.request_id,
            cap_name: m.cap_name,
            server_name: m.server_name,
            tool_name: m.tool_name,
            args_preview: m.args_preview ?? '',
          });
        }
        break;
      }

      default:
        console.warn('[WS] unknown message type:', msg.type);
    }
  }, [store, playNextAudio]);

  const connect = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    store.getState().setConnection('connecting');
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[WS] connected');
      reconnectAttemptsRef.current = 0;
      store.getState().setConnection('connected');
      // 第三刀 · 喂 appReady 第 4 路 · WS onopen 即翻 true · disconnected 翻回 false
      store.getState().setWsReady(true);
    };

    ws.onmessage = (ev) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(ev.data as string);
      } catch (e) {
        console.error('[WS] parse error:', e);
        return;
      }
      if (typeof parsed === 'object' && parsed !== null && 'type' in parsed) {
        handleMessage(parsed as WsMessage);
      }
    };

    ws.onclose = () => {
      console.log('[WS] disconnected');
      store.getState().setConnection('disconnected');
      store.getState().setWsReady(false);
      // 2026-06-15 batch 2 [confirm 边界] · WS 断 · 清挂起 confirm queue ·
      // 后端 deny_all_pending 已处理孤儿 capability handler · 前端 modal 不
      // 该再弹(用户没法 accept · 后端也不再 await)。
      store.getState().clearMcpConfirmQueue();
      wsRef.current = null;
      const delay = Math.min(
        RECONNECT_BASE_MS * Math.pow(2, reconnectAttemptsRef.current),
        RECONNECT_MAX_MS,
      );
      reconnectAttemptsRef.current += 1;
      console.log(`[WS] reconnecting in ${delay}ms...`);
      reconnectTimerRef.current = window.setTimeout(connect, delay);
    };

    ws.onerror = () => {
      // onclose 会接着触发，由 onclose 负责重连逻辑
    };
  }, [store, handleMessage]);

  // v3-G chunk 4 Part C: heartbeat 给 long_idle trigger 用。仅在
  // visibility=visible + focus 时每 15s ping；离开页面立即停。后端 grace
  // 30s 内 = "在前台"。无新装依赖；纯 fetch。
  useEffect(() => {
    let timer: number | null = null;
    let cancelled = false;
    const userId = store.getState().defaultUserId || 'default';

    async function pingOnce() {
      if (cancelled) return;
      try {
        await fetch('http://127.0.0.1:8000/api/heartbeat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId }),
        });
      } catch {
        // 后端不可达 best-effort 忽略
      }
    }
    function shouldPing(): boolean {
      return typeof document !== 'undefined'
        && document.visibilityState === 'visible'
        && document.hasFocus();
    }
    function startLoop() {
      stopLoop();
      if (!shouldPing()) return;
      pingOnce();
      timer = window.setInterval(() => {
        if (shouldPing()) pingOnce();
        else stopLoop();
      }, 15_000);
    }
    function stopLoop() {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    }
    function onVisChange() {
      if (shouldPing()) startLoop();
      else stopLoop();
    }

    startLoop();
    document.addEventListener('visibilitychange', onVisChange);
    window.addEventListener('focus', onVisChange);
    window.addEventListener('blur', onVisChange);
    return () => {
      cancelled = true;
      stopLoop();
      document.removeEventListener('visibilitychange', onVisChange);
      window.removeEventListener('focus', onVisChange);
      window.removeEventListener('blur', onVisChange);
    };
  }, [store]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimerRef.current !== null) clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) {
        // 置空 onclose 防止 cleanup 触发重连
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sendText = useCallback((content: string) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      console.warn('[WS] not connected, drop text');
      return;
    }
    textChunkCountRef.current = 0;
    const s = store.getState();
    s.setLastSendTimestamp(performance.now());
    // v3-F：新一轮开始，先清掉上一轮的内心独白
    s.clearCurrentThinking();
    // v3-E1 step5：新一轮开始，清掉上一轮的 emotion
    s.clearCurrentEmotion();
    // v3-E1 step6：新一轮开始，清掉上一轮的 motion
    s.clearCurrentMotion();
    // UX-004:新一轮开始,清掉上一轮残留的 tool loading(理论上 tool_use_done
    // 已经清过,这里是 belt-and-suspenders 防 backend 路径异常未发 done)
    s.setCurrentToolName(null);
    // 乐观更新：立刻显示 user 气泡
    s.appendChatMessage({
      id: newClientId('u'),
      role: 'user',
      content,
      streaming: false,
      ts: performance.now(),
      // sendText 永远是用户主动文字输入
      kind: 'normal',
    });
    console.log(`[FRONT] send text len=${content.length}`);
    ws.send(JSON.stringify({
      type: 'text',
      content,
      user_id: s.defaultUserId,
      conversation_id: s.currentConversationId,
      character_id: s.currentCharacterId,
    }));
  }, [store]);

  const sendVoice = useCallback((audioBase64: string) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      console.warn('[WS] not connected, drop voice');
      return;
    }
    textChunkCountRef.current = 0;
    const s = store.getState();
    s.setLastSendTimestamp(performance.now());
    // v3-F：新一轮开始，先清掉上一轮的内心独白
    s.clearCurrentThinking();
    // v3-E1 step5：新一轮开始，清掉上一轮的 emotion
    s.clearCurrentEmotion();
    // v3-E1 step6：新一轮开始，清掉上一轮的 motion
    s.clearCurrentMotion();
    // UX-004:新一轮开始,清掉上一轮残留的 tool loading(理论上 tool_use_done
    // 已经清过,这里是 belt-and-suspenders 防 backend 路径异常未发 done)
    s.setCurrentToolName(null);
    console.log(`[FRONT] send voice b64_len=${audioBase64.length}`);
    // 语音的 user 气泡等 asr_result 携带 message_id 时一起插入，
    // 避免内容为空的占位气泡。
    ws.send(JSON.stringify({
      type: 'voice',
      audio: audioBase64,
      user_id: s.defaultUserId,
      conversation_id: s.currentConversationId,
      character_id: s.currentCharacterId,
    }));
  }, [store]);

  // 2026-06-15 ⑤ · MCP tool 确认 modal 回应 · MCPConfirmModal accept/reject
  // 按钮调它 · 发 mcp_tool_confirm_response 帧 + shift 队首 · 下一条自动弹。
  const sendMcpToolConfirmResponse = useCallback(
    (requestId: string, accept: boolean) => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        console.warn('[WS] not connected, drop mcp confirm response');
        // 即使 WS 断开也 shift 出队(防 UI 卡在已无效 modal)· 后端 deny_all_pending
        // 已经处理孤儿。
        store.getState().shiftMcpConfirm(requestId);
        return;
      }
      ws.send(JSON.stringify({
        type: 'mcp_tool_confirm_response',
        request_id: requestId,
        accept,
      }));
      store.getState().shiftMcpConfirm(requestId);
    },
    [store],
  );

  const sendInterrupt = useCallback(() => {
    const ws = wsRef.current;
    const s = store.getState();

    // 本地立即生效：清音频播放队列，标 streaming 收尾，UI 切 interrupted。
    // 后端那边 await receive_json 会拿到 {"type":"interrupt"}，我们不等
    // 后端 done 才停播放——延迟太大体感差。
    audioQueueRef.current = [];
    // v3-E1 step4：撤当前段的 playback timeout，防迟到触发 playNextAudio
    if (playbackTimeoutRef.current !== null) {
      clearTimeout(playbackTimeoutRef.current);
      playbackTimeoutRef.current = null;
    }
    if (s.streamingMessageId !== null) {
      s.finishChatMessage(s.streamingMessageId);
      s.setStreamingMessageId(null);
    }
    if (s.muteWhileSpeaking && s.micMuted) s.setMicMuted(false);
    s.setStatus('interrupted');
    window.setTimeout(() => {
      const cur = useAppStore.getState().status;
      if (cur === 'interrupted') useAppStore.getState().setStatus('idle');
    }, 1500);

    if (!ws || ws.readyState !== WebSocket.OPEN) {
      console.warn('[WS] not connected, drop interrupt (local-only)');
      return;
    }
    console.log('[FRONT] send interrupt');
    ws.send(JSON.stringify({ type: 'interrupt' }));
  }, [store]);

  const sendTouch = useCallback(() => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      console.warn('[WS] not connected, drop touch');
      return;
    }
    const s = store.getState();

    // 局部立即生效：上一轮如果还在播音 / 还有 streaming 气泡，先收掉，
    // 避免与新一轮的 audio_chunk / text_chunk 混在一起。后端那边
    // _handle_message 主循环也会自动 cancel 上一轮 turn task。
    audioQueueRef.current = [];
    // v3-E1 step4：撤当前段的 playback timeout，防迟到触发 playNextAudio
    if (playbackTimeoutRef.current !== null) {
      clearTimeout(playbackTimeoutRef.current);
      playbackTimeoutRef.current = null;
    }
    if (s.streamingMessageId !== null) {
      s.finishChatMessage(s.streamingMessageId);
      s.setStreamingMessageId(null);
    }
    if (s.muteWhileSpeaking && s.micMuted) s.setMicMuted(false);

    textChunkCountRef.current = 0;
    s.setLastSendTimestamp(performance.now());
    s.clearCurrentThinking();
    // v3-E1 step5：新一轮开始，清掉上一轮的 emotion
    s.clearCurrentEmotion();
    // v3-E1 step6：新一轮开始，清掉上一轮的 motion
    s.clearCurrentMotion();

    console.log('[FRONT] send touch');
    ws.send(JSON.stringify({
      type: 'touch',
      user_id: s.defaultUserId,
      conversation_id: s.currentConversationId,
      character_id: s.currentCharacterId,
    }));
  }, [store]);

  const sendCharacterSwitch = useCallback(
    (characterId: number, conversationId: number | null) => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        console.warn('[WS] not connected, drop character_switch');
        return;
      }
      const s = store.getState();
      console.log(
        `[FRONT] send character_switch char=${characterId} conv=${conversationId}`,
      );
      ws.send(JSON.stringify({
        type: 'character_switch',
        user_id: s.defaultUserId,
        character_id: characterId,
        conversation_id: conversationId,
      }));
    },
    [store],
  );

  const isConnected = useCallback(() => {
    return wsRef.current?.readyState === WebSocket.OPEN;
  }, []);

  return {
    sendText, sendVoice, sendInterrupt, sendTouch, sendCharacterSwitch,
    sendMcpToolConfirmResponse,
    isConnected,
  };
}
