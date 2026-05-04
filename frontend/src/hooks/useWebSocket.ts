import { useEffect, useRef, useCallback } from 'react';
import { useAppStore } from '../store';

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
    next.onended = () => {
      isPlayingRef.current = false;
      playNextAudio();
    };
    next.onerror = () => {
      isPlayingRef.current = false;
      playNextAudio();
    };
    next.play().catch(() => {
      isPlayingRef.current = false;
      playNextAudio();
    });
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

        // 流式 assistant 气泡收尾
        if (s.streamingMessageId !== null) {
          s.finishChatMessage(s.streamingMessageId);
          s.setStreamingMessageId(null);
        }

        // v3-F #4：清空音频播放队列，立即停下当前正在播的句
        audioQueueRef.current = [];
        if (s.muteWhileSpeaking && s.micMuted) s.setMicMuted(false);

        if (interruptedFlag) {
          // 标 'interrupted' 视觉，1.5s 后回 idle（保留视觉反馈给用户）
          s.setStatus('interrupted');
          window.setTimeout(() => {
            const cur = useAppStore.getState().status;
            // 若期间用户又开了新一轮，不要把它从 thinking 拽回 idle
            if (cur === 'interrupted') useAppStore.getState().setStatus('idle');
          }, 1500);
        } else if (s.status === 'thinking') {
          // 纯文字回复（无 audio_chunk）会卡 thinking，这里兜底
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
