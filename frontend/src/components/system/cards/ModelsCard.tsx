import { useCallback, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import {
  listProvidersByType,
  type AIProvider,
} from '../../../lib/ai_providers';
import { fetchSystemResources, type SystemResources } from '../../../lib/observability';
import Card from './Card';

const BACKEND_BASE = 'http://127.0.0.1:8000';

interface AsrConfig { whisper_model_size: string }

async function fetchAsrConfig(): Promise<AsrConfig> {
  const r = await fetch(`${BACKEND_BASE}/api/config/asr`);
  if (!r.ok) throw new Error(`fetch /api/config/asr failed: ${r.status}`);
  return (await r.json()) as AsrConfig;
}

function pickActive(groups: { vendors: { id: string; name: string; providers: AIProvider[] }[]; ungrouped: AIProvider[] }): { active: AIProvider | null; vendorName: string | null } {
  for (const v of groups.vendors) {
    for (const p of v.providers) {
      if (p.is_active) return { active: p, vendorName: v.name };
    }
  }
  for (const p of groups.ungrouped) {
    if (p.is_active) return { active: p, vendorName: null };
  }
  return { active: null, vendorName: null };
}

export default function ModelsCard() {
  const [llmActive, setLlmActive]   = useState<{ p: AIProvider | null; vendor: string | null }>({ p: null, vendor: null });
  const [ttsActive, setTtsActive]   = useState<{ p: AIProvider | null; vendor: string | null }>({ p: null, vendor: null });
  const [asr, setAsr]               = useState<AsrConfig | null>(null);
  const [sysRes, setSysRes]         = useState<SystemResources | null>(null);
  const [loading, setLoading]       = useState(false);
  const [err, setErr]               = useState<string | null>(null);
  const [lastAt, setLastAt]         = useState<number | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const [llmRes, ttsRes, asrRes, sysResp] = await Promise.allSettled([
        listProvidersByType('llm'),
        listProvidersByType('tts'),
        fetchAsrConfig(),
        fetchSystemResources(),
      ]);
      if (llmRes.status === 'fulfilled') {
        const { active, vendorName } = pickActive(llmRes.value);
        setLlmActive({ p: active, vendor: vendorName });
      }
      if (ttsRes.status === 'fulfilled') {
        const { active, vendorName } = pickActive(ttsRes.value);
        setTtsActive({ p: active, vendor: vendorName });
      }
      if (asrRes.status === 'fulfilled') setAsr(asrRes.value);
      if (sysResp.status === 'fulfilled') setSysRes(sysResp.value);
      const failed = [llmRes, ttsRes, asrRes, sysResp].filter(r => r.status === 'rejected');
      if (failed.length > 0) {
        const first = failed[0] as PromiseRejectedResult;
        setErr(String(first.reason));
      }
      setLastAt(Date.now());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const llmLine = llmActive.p
    ? `${llmActive.p.name}${llmActive.p.model ? ' · ' + llmActive.p.model : ''}${llmActive.vendor ? ` (${llmActive.vendor})` : ''}`
    : '— 无 active';
  const ttsLine = ttsActive.p
    ? `${ttsActive.p.name}${ttsActive.p.model ? ' · ' + ttsActive.p.model : ''}${ttsActive.vendor ? ` (${ttsActive.vendor})` : ''}`
    : '— 无 active';

  const refreshBtn = (
    <button
      type="button"
      onClick={() => void refresh()}
      disabled={loading}
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded hover:opacity-80 disabled:opacity-50"
      style={{ color: 'var(--color-text-secondary)' }}
      aria-label="刷新模型状态"
    >
      <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
      刷新
    </button>
  );

  return (
    <Card title="🧠 模型" rightSlot={refreshBtn}>
      <div className="space-y-3 text-xs">
        <div>
          <div className="flex items-baseline justify-between">
            <span style={{ color: 'var(--color-text-secondary)' }}>LLM (active)</span>
          </div>
          <div className="font-mono text-[11px] mt-0.5 break-all"
            style={{ color: 'var(--color-text-primary)' }}>
            {llmLine}
          </div>
        </div>

        <div>
          <div className="flex items-baseline justify-between">
            <span style={{ color: 'var(--color-text-secondary)' }}>ASR · Faster Whisper</span>
          </div>
          <div className="font-mono text-[11px] mt-0.5"
            style={{ color: 'var(--color-text-primary)' }}>
            size: {asr?.whisper_model_size ?? '?'}
            {' · '}
            <span style={{
              color: sysRes?.whisper_loaded ? 'rgb(34, 197, 94)' : 'var(--color-text-secondary)',
            }}>
              {sysRes?.whisper_loaded ? '已加载' : '未加载 (lazy)'}
            </span>
            {sysRes?.whisper_disk_mb != null && (
              <span style={{ color: 'var(--color-text-secondary)' }}>
                {' · '}{sysRes.whisper_disk_mb} MB
              </span>
            )}
          </div>
        </div>

        <div>
          <div className="flex items-baseline justify-between">
            <span style={{ color: 'var(--color-text-secondary)' }}>TTS (active)</span>
          </div>
          <div className="font-mono text-[11px] mt-0.5 break-all"
            style={{ color: 'var(--color-text-primary)' }}>
            {ttsLine}
          </div>
        </div>

        {err && (
          <p className="text-[11px]" style={{ color: 'rgb(239, 68, 68)' }}>
            部分接口失败:{err}
          </p>
        )}
        {lastAt && (
          <p className="text-[10px]" style={{ color: 'var(--color-text-secondary)', opacity: 0.7 }}>
            {new Date(lastAt).toLocaleTimeString()} · 不自动刷新,改完模型记得点上方刷新。
          </p>
        )}
      </div>
    </Card>
  );
}
