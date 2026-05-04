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
}

interface UseWebSocketReturn {
  sendText: (content: string) => void;
  sendVoice: (audioBase64: string) => void;
  // v3-F #4：通知后端取消当前 LLM stream + TTS playback
  sendInterrupt: () => void;
  // v3-E1 step3：用户点 Live2D canvas，触发后端主动对话
  sendTouch: () => void;
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
          });
          s.setStreamingMessageId(id);
        } else {
          s.appendChatMessageContent(s.streamingMessageId, chunk);
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

      case 'thinking': {
        // v3-F：AI 内心独白，每轮最多一次。UI 显示在 StatusBadge 旁
        const value = msg.value ?? '';
        if (value) s.setCurrentThinking(value);
        break;
      }

      case 'notify':
        s.pushNotification({ type: 'notify', content: msg.content ?? '' });
        break;

      case 'alarm':
        s.pushNotification({ type: 'alarm', content: msg.content ?? '', todoId: msg.todo_id });
        break;

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
    // 乐观更新：立刻显示 user 气泡
    s.appendChatMessage({
      id: newClientId('u'),
      role: 'user',
      content,
      streaming: false,
      ts: performance.now(),
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

    console.log('[FRONT] send touch');
    ws.send(JSON.stringify({
      type: 'touch',
      user_id: s.defaultUserId,
      conversation_id: s.currentConversationId,
      character_id: s.currentCharacterId,
    }));
  }, [store]);

  const isConnected = useCallback(() => {
    return wsRef.current?.readyState === WebSocket.OPEN;
  }, []);

  return { sendText, sendVoice, sendInterrupt, sendTouch, isConnected };
}
