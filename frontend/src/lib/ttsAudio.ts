// v3-E1 step4: TTS-side AudioContext singleton（与 useAudio.ts 的麦克风 ctx 分离）。
//
// 架构定位：
// - useAudio.ts 的 ctx 处理麦克风输入流（ASR / VAD / 打断检测），lazily 创建于
//   首次开麦时。
// - 这里的 ctx 处理 TTS 音频输出流的实时分析（Live2D 口型同步），lazily 创建
//   于首次有 audio_chunk 到达时。
//
// 为什么是两个 ctx：
// - 输入图（mic stream → analyser）和输出图（HTMLAudioElement → analyser →
//   destination）职责分离，互不依赖。
// - mic ctx 不存在的场景（用户从未开麦）下口型仍然能工作。
// - Chrome 单页 AudioContext 上限 ≈ 6，2 个安全在内。
//
// 关键陷阱：
// - createMediaElementSource 对同一 HTMLAudioElement 只能调一次，再调抛
//   InvalidStateError。useWebSocket 每条 audio_chunk new 一个新元素，所以
//   一对一 pipe 即可。pipeAudioElement 仍 try/catch 兜底。
// - 一旦 createMediaElementSource 被调用，该 audio 元素的输出会被 WebAudio
//   图劫持 —— 必须把 analyser 连到 ctx.destination 才听得见。

let _ctx: AudioContext | null = null;
let _analyser: AnalyserNode | null = null;

type WebkitWindow = Window & { webkitAudioContext?: typeof AudioContext };

export function getTtsAnalyser(): AnalyserNode {
  if (_ctx === null || _analyser === null) {
    const Ctor =
      window.AudioContext ?? (window as WebkitWindow).webkitAudioContext;
    if (!Ctor) {
      throw new Error('Web Audio API not supported');
    }
    _ctx = new Ctor();
    _analyser = _ctx.createAnalyser();
    _analyser.fftSize = 256;
    // 我们在 useAudioAmplitude 里自己做指数移动平均，不让 analyser 再叠加一次
    _analyser.smoothingTimeConstant = 0;
    _analyser.connect(_ctx.destination);
  }
  return _analyser;
}

export function pipeAudioElement(audioEl: HTMLAudioElement): void {
  let analyser: AnalyserNode;
  try {
    analyser = getTtsAnalyser();
  } catch (err) {
    console.warn('[ttsAudio] no Web Audio API, lipsync disabled', err);
    return;
  }

  const ctx = analyser.context as AudioContext;
  try {
    const src = ctx.createMediaElementSource(audioEl);
    src.connect(analyser);
  } catch (err) {
    // 同一元素被 pipe 两次 / element 已被销毁，记日志不抛
    console.warn('[ttsAudio] pipeAudioElement failed', err);
    return;
  }

  // Chrome 在用户首次交互前 ctx 处于 suspended，此处兜底 resume。
  // 用户在 Skyler 里至少要点过发送 / 启动一次才会触发 TTS，所以 user
  // activation 一定到位，resume 不会被 autoplay policy 拒。
  if (ctx.state === 'suspended') {
    void ctx.resume().catch((err) => {
      console.warn('[ttsAudio] ctx.resume failed', err);
    });
  }
}
