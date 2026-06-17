// INV (2026-06-11) · GSV Model add/edit modal
//
// PM SPEC-LOCK:
//   - 不含 server_url 字段(全局走 ai_providers · 卡顶单独输入)
//   - 不含 emotion 列表(动态来源 = lab_dir/*.lab glob · 加 model 后单独 upload .lab)
//   - 字段:model_id (业务 key · create 后 PATCH 不可改)/ label / mode (trained|zeroshot)/
//          tts_language / gpt_weights / sovits_weights / lab_dir / wav_remote_dir /
//          default_emotion / inference_params (JSON 文本框)
//   - 编辑模式:model_id disabled · 其余可改
//
// 复用 LLM 的 AddModelModal 视觉风格(rounded-lg / w-[460px] / 输入 inputStyle / 标题深字 + 副灰说明)。
import { useEffect, useState } from 'react';
import {
  type TtsModel,
  createTtsModel,
  patchTtsModel,
} from '../../lib/tts_models';

interface Props {
  editing: TtsModel | null;
  onClose: () => void;
  onSaved: () => void;
  showToast: (text: string) => void;
}

export default function AddGsvModelModal({
  editing, onClose, onSaved, showToast,
}: Props) {
  const isEdit = editing !== null;

  const [modelId, setModelId] = useState(editing?.model_id ?? '');
  const [label, setLabel] = useState(editing?.label ?? '');
  const [mode, setMode] = useState<string>(editing?.mode ?? 'trained');
  const [ttsLanguage, setTtsLanguage] = useState<string>(editing?.tts_language ?? 'ja');
  const [gptWeights, setGptWeights] = useState(editing?.gpt_weights ?? '');
  const [sovitsWeights, setSovitsWeights] = useState(editing?.sovits_weights ?? '');
  const [labDir, setLabDir] = useState(editing?.lab_dir ?? '');
  const [wavRemoteDir, setWavRemoteDir] = useState(editing?.wav_remote_dir ?? '');
  const [defaultEmotion, setDefaultEmotion] = useState(editing?.default_emotion ?? '');
  const [inferenceParamsText, setInferenceParamsText] = useState<string>(
    editing?.inference_params
      ? JSON.stringify(editing.inference_params, null, 2)
      : '{\n  "top_k": 15,\n  "top_p": 1.0,\n  "temperature": 1.0,\n  "speed_factor": 1.0\n}',
  );
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (editing) {
      setModelId(editing.model_id);
      setLabel(editing.label);
      setMode(editing.mode ?? 'trained');
      setTtsLanguage(editing.tts_language ?? 'ja');
      setGptWeights(editing.gpt_weights ?? '');
      setSovitsWeights(editing.sovits_weights ?? '');
      setLabDir(editing.lab_dir ?? '');
      setWavRemoteDir(editing.wav_remote_dir ?? '');
      setDefaultEmotion(editing.default_emotion ?? '');
      setInferenceParamsText(
        editing.inference_params
          ? JSON.stringify(editing.inference_params, null, 2)
          : '',
      );
    }
  }, [editing]);

  const inputStyle = {
    background: 'var(--color-bg-input)',
    border: '1px solid var(--color-border)',
    color: 'var(--color-text-primary)',
  } as const;

  const onSubmit = async () => {
    if (!modelId.trim()) { showToast('model_id 必填'); return; }
    if (!label.trim()) { showToast('label 必填'); return; }
    let inferenceParams: Record<string, unknown> | undefined;
    if (inferenceParamsText.trim()) {
      try {
        const parsed = JSON.parse(inferenceParamsText);
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
          showToast('inference_params 必须是 JSON 对象');
          return;
        }
        inferenceParams = parsed as Record<string, unknown>;
      } catch (e) {
        showToast(`inference_params JSON 解析失败:${(e as Error).message}`);
        return;
      }
    }
    setSubmitting(true);
    try {
      if (isEdit && editing) {
        await patchTtsModel(editing.id, {
          label: label.trim(),
          mode: mode || undefined,
          tts_language: (ttsLanguage as 'zh' | 'ja' | 'en') || undefined,
          gpt_weights: gptWeights.trim() || undefined,
          sovits_weights: sovitsWeights.trim() || undefined,
          lab_dir: labDir.trim() || undefined,
          wav_remote_dir: wavRemoteDir.trim() || undefined,
          default_emotion: defaultEmotion.trim() || undefined,
          inference_params: inferenceParams,
        });
        showToast(`已更新 ${label.trim()}`);
      } else {
        await createTtsModel({
          provider: 'gsv',
          model_id: modelId.trim(),
          label: label.trim(),
          mode: mode || undefined,
          tts_language: (ttsLanguage as 'zh' | 'ja' | 'en') || undefined,
          gpt_weights: gptWeights.trim() || undefined,
          sovits_weights: sovitsWeights.trim() || undefined,
          lab_dir: labDir.trim() || undefined,
          wav_remote_dir: wavRemoteDir.trim() || undefined,
          default_emotion: defaultEmotion.trim() || undefined,
          inference_params: inferenceParams,
        });
        showToast(`已添加 ${label.trim()}`);
      }
      onSaved();
    } catch (e) {
      showToast(`${isEdit ? '更新' : '添加'}失败:${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[55] flex items-center justify-center"
      style={{ background: 'color-mix(in srgb, var(--color-bg-base) 60%, transparent)' }}
      onClick={onClose}
    >
      <div
        className="rounded-lg p-5 w-[560px] max-h-[90vh] overflow-y-auto shadow-2xl"
        style={{ background: 'var(--color-bg-surface)', border: '1px solid var(--color-border)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-medium mb-1"
          style={{ color: 'var(--color-text-primary)' }}>
          {isEdit ? '编辑 GSV 模型' : '添加 GSV 模型'}
        </h2>
        <p className="text-[11px] mb-4"
          style={{ color: 'var(--color-text-secondary)' }}>
          server_url 与 emotion 列表本表单不含 · 前者走卡顶全局 · 后者按 lab_dir 自动从
          .lab 文件派生(添加模型后,情绪覆盖区可见缺失项)。
        </p>

        <div className="space-y-3 text-sm">
          <Row label="model_id (业务 key · 不可改)">
            <input
              className="w-full rounded-md px-2 py-1.5 text-xs"
              style={inputStyle}
              value={modelId}
              disabled={isEdit}
              onChange={(e) => setModelId(e.target.value)}
              placeholder="e.g. ayaka_v4"
            />
          </Row>
          <Row label="label (显示名)">
            <input
              className="w-full rounded-md px-2 py-1.5 text-xs" style={inputStyle}
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Ayaka v4(神里绫华 ja)"
            />
          </Row>

          <div className="grid grid-cols-2 gap-3">
            <Row label="mode">
              <select
                className="w-full rounded-md px-2 py-1.5 text-xs" style={inputStyle}
                value={mode} onChange={(e) => setMode(e.target.value)}
              >
                <option value="trained">trained</option>
                <option value="zeroshot">zeroshot</option>
              </select>
            </Row>
            <Row label="tts_language">
              <select
                className="w-full rounded-md px-2 py-1.5 text-xs" style={inputStyle}
                value={ttsLanguage} onChange={(e) => setTtsLanguage(e.target.value)}
              >
                <option value="ja">ja</option>
                <option value="zh">zh</option>
                <option value="en">en</option>
              </select>
            </Row>
          </div>

          <Row label="gpt_weights (server 端权重路径)">
            <input
              className="w-full rounded-md px-2 py-1.5 text-xs font-mono" style={inputStyle}
              value={gptWeights}
              onChange={(e) => setGptWeights(e.target.value)}
              placeholder="GPT_weights_v4/<name>-e15.ckpt"
            />
          </Row>
          <Row label="sovits_weights (server 端权重路径)">
            <input
              className="w-full rounded-md px-2 py-1.5 text-xs font-mono" style={inputStyle}
              value={sovitsWeights}
              onChange={(e) => setSovitsWeights(e.target.value)}
              placeholder="SoVITS_weights_v4/<name>_e5_s1380_l32.pth"
            />
          </Row>
          <Row label="lab_dir (本地 .lab 缓存目录 · repo 相对)">
            <input
              className="w-full rounded-md px-2 py-1.5 text-xs font-mono" style={inputStyle}
              value={labDir}
              onChange={(e) => setLabDir(e.target.value)}
              placeholder="tts/gsv/<model_id>"
            />
          </Row>
          <Row label="wav_remote_dir (server 端 wav 目录 · 含 trailing /)">
            <input
              className="w-full rounded-md px-2 py-1.5 text-xs font-mono" style={inputStyle}
              value={wavRemoteDir}
              onChange={(e) => setWavRemoteDir(e.target.value)}
              placeholder="/workspace/GSVI/<name>_emotion_bank/"
            />
          </Row>
          <Row label="default_emotion (LLM 输出未命中集合时回落)">
            <input
              className="w-full rounded-md px-2 py-1.5 text-xs" style={inputStyle}
              value={defaultEmotion}
              onChange={(e) => setDefaultEmotion(e.target.value)}
              placeholder="日常"
            />
          </Row>
          <Row label="inference_params (JSON 对象)">
            <textarea
              className="w-full rounded-md px-2 py-1.5 text-xs font-mono"
              style={{ ...inputStyle, minHeight: 110 }}
              value={inferenceParamsText}
              onChange={(e) => setInferenceParamsText(e.target.value)}
            />
          </Row>
        </div>

        <div className="flex justify-end gap-2 mt-5">
          <button
            type="button" onClick={onClose}
            className="text-xs px-3 py-1.5 rounded-md"
            style={{ background: 'var(--color-bg-elevated)', color: 'var(--color-text-primary)' }}
          >
            取消
          </button>
          <button
            type="button" onClick={() => void onSubmit()} disabled={submitting}
            className="text-xs px-3 py-1.5 rounded-md disabled:opacity-50"
            style={{ background: 'var(--color-accent)', color: 'var(--color-bubble-user-text)' }}
          >
            {submitting ? '…' : (isEdit ? '保存' : '添加')}
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] mb-1"
        style={{ color: 'var(--color-text-secondary)' }}>
        {label}
      </div>
      {children}
    </div>
  );
}
