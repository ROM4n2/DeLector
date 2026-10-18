/**
 * wb-tts.js —— 单词发音子系统（C7 Task 5 · 块 1：tts-audio，锚点密度最低处）
 *
 * 本文件内容从 static/german/workbench.html 的内联脚本**逐字节**搬出，未改写一个字符：
 *   1) `_tts*` 七个状态声明，连同其上方「单词发音」分节 banner；
 *   2) `playWord()`，连同其 JSDoc 与内部的 tryServer / trySpeech / tryOnline 三条链路。
 * 搬动前后唯一新增的字节是本段说明性文件头。
 *
 * 引入方式：入口页用**普通** <script src> 加载，加载序为
 *     wb-seed-data.js  →  wb-tts.js  →  主内联脚本
 * 刻意不用 ES Module：Android/WebView 的模块加载语义未真机验证（计划 Fog of War
 * Unknown 2），必须保留整体回退成内联脚本的能力。本文件零 import / export。
 *
 * 跨文件依赖（全部在**运行期**解析；它们都是主内联脚本的顶层声明，同处全局词法环境）：
 *   stripDeArticle() / pickDeVoice() / EMBEDDED_AUDIO / S / console
 * => playWord 只能在主内联脚本解析完成之后被调用（UI click 触发）。
 *    任何「在加载期调用 playWord」的写法都会撞上 TDZ / undefined，不要加。
 * => 反向也成立：主内联脚本仍可在运行期读写 `_tts*` —— 顶层 let/const 落在同一
 *    全局词法环境（不挂 window），故 voiceschanged 回调里写 _ttsVoice 依然有效。
 */

/* ======================================================================
 * 单词发音（server TTS（DeLector 服务端）优先 → 在线多源 → Web Speech API 兜底；单实例互斥，防并发）
 * ==================================================================== */
const _ttsAudio = typeof Audio !== 'undefined' ? new Audio() : null;   // 全局单实例
let _ttsBusy = false;          // 防止连点重入（内部标志）
let _ttsGestureUnlocked = false;  // 移动端 autoplay 策略解锁标志：用户手动点一次即 true
let _ttsVoice = null;          // pickDeVoice 结果缓存（懒加载）
let _ttsServerReachable = typeof location !== 'undefined' && location.protocol.startsWith('http');
let _ttsVoicesReady = false;   // speechSynthesis.onvoiceschanged 是否已触发
let _ttsAttemptId = 0;         // 每次 playWord 递增，stale handler 检测到 ID 不匹配直接退出

/**
 * 播放单词发音（纯德语原词）。
 * 遵循：DeLector 服务端 TTS 优先（http(s) 下 engine == 'auto' 先走 tryServer），失败回落在线多源，再回落 Web Speech。
 * 永远 resolve 结构化对象（不 reject，避免调用方漏 catch 导致 unhandled rejection）。
 * 全局单实例互斥：新一次 playWord 到来，立即打断上一次。
 * 移动端 Chrome NotAllowedError 通过"play() 必须在 click 栈同步调用"规避（调用方保证）。
 *
 * @param {string} hw - 词头（可能含冠词/标点）
 * @param {{engine?:'auto'|'server'|'online'|'speech', rate?:number, preferHwOnly?:boolean}} opts
 * @returns {Promise<{ok:boolean, engine:'embedded'|'server'|'online'|'speech'|null, error?:string, duration?:number}>}
 */
function playWord(hw, opts) {
  opts = opts || {};
  const engine = opts.engine || 'auto';   // auto | online | speech
  const rate = typeof opts.rate === 'number' ? opts.rate : (S.settings.tts && S.settings.tts.rate) || 0.9;
  const word = stripDeArticle(hw);
  console.log("[TTS] playWord start:", { hw, word, engine, rate, hasAudio: !!_ttsAudio, hasSpeech: typeof speechSynthesis !== 'undefined' });
  if (!word) return Promise.resolve({ ok: false, engine: null, error: "empty-word" });
  if (S.settings.tts && S.settings.tts.engine === 'off') {
    return Promise.resolve({ ok: false, engine: null, error: "tts-off" });
  }

  // ---- 互斥：立即停掉上一次播放 ----
  try {
    if (_ttsAudio) { _ttsAudio.pause(); try { _ttsAudio.removeAttribute('src'); } catch (e) {} }
    if (typeof speechSynthesis !== 'undefined') speechSynthesis.cancel();
  } catch (e) { /* ignore */ }
  _ttsBusy = true;
  // gesture unlock：playWord 被调用即认为是从用户手势栈发起（UI 按钮 click）
  _ttsGestureUnlocked = true;
  const myAttempt = ++_ttsAttemptId;

  const finalResolve = (result) => {
    _ttsBusy = false;
    return result;
  };

  // ---- 优先级最高：内嵌 base64 音频词典（零网络、零依赖、Android content:// 兜底） ----
  // EMBEDDED_AUDIO 的键全部小写（与 CORE_VOCAB_DB 一致），但 stripDeArticle 保留
  // 原始大写（Adresse、Bahnhof 等名词首字母不被动）。必须归一到小写才能命中名词。
  const embeddedKey = word.toLowerCase();
  if (EMBEDDED_AUDIO && EMBEDDED_AUDIO[embeddedKey]) {
    console.log("[TTS] hit embedded audio:", word, "size:", (EMBEDDED_AUDIO[embeddedKey].length * 0.75) | 0, "bytes");
    return new Promise((innerRes) => {
      try {
        const audio = _ttsAudio || new Audio();
        // 上一段已 pause/clean，这里直接设 src
        const url = "data:audio/mpeg;base64," + EMBEDDED_AUDIO[embeddedKey];
        let settled = false;
        const cleanup = () => {
          audio.removeEventListener("playing", onPlay);
          audio.removeEventListener("error", onErr);
          clearTimeout(timer);
        };
        const onPlay = () => {
          if (settled) return; settled = true; cleanup();
          console.log("[TTS] embedded playing");
          // 等播放结束才返回
          audio.addEventListener("ended", () => innerRes(finalResolve({ ok: true, engine: "embedded" })), { once: true });
          // 兜底：5 秒后强制返回
          setTimeout(() => innerRes(finalResolve({ ok: true, engine: "embedded" })), 3000);
        };
        const onErr = (e) => {
          if (settled) return; settled = true; cleanup();
          console.warn("[TTS] embedded error:", e);
          innerRes(finalResolve({ ok: false, engine: "embedded", error: "audio-error" }));
        };
        const timer = setTimeout(() => {
          if (settled) return; settled = true; cleanup();
          console.warn("[TTS] embedded timeout");
          innerRes(finalResolve({ ok: false, engine: "embedded", error: "timeout" }));
        }, 5000);
        audio.addEventListener("playing", onPlay);
        audio.addEventListener("error", onErr);
        audio.src = url;
        audio.load();
        const p = audio.play();
        if (p && p.catch) p.catch((e) => {
          if (settled) return; settled = true; cleanup();
          console.warn("[TTS] embedded play() rejected:", e);
          innerRes(finalResolve({ ok: false, engine: "embedded", error: "play-rejected" }));
        });
      } catch (e) {
        console.warn("[TTS] embedded exception:", e);
        innerRes(finalResolve({ ok: false, engine: "embedded", error: "exception" }));
      }
    });
  }

  // ---- 优先级 0.5：DeLector 服务端 TTS（GET /api/audio/tts，服务端 edge-tts 生成） ----
  // 仅 http(s) 协议下可用；file:// / content:// 下 _ttsServerReachable 为 false 直接跳过，
  // 不等超时。移动浏览器在 file:// 协议下禁 TTS API，而嵌入 DeLector 后本页跑在
  // http://<desktop-ip>:8000 下，此限制消失 —— 这是集成后移动端能出声的关键路径。
  // 与在线 TTS 共用 _ttsAudio 单实例（playWord 入口已统一 pause/clean）。
  const tryServer = () => new Promise((innerRes) => {
    if (!_ttsServerReachable || !_ttsAudio) {
      console.warn("[TTS] server skipped: reachable=" + _ttsServerReachable + " audio=" + !!_ttsAudio);
      return innerRes(finalResolve({ ok: false, engine: 'server', error: "no-server" }));
    }
    const ratePercent = Math.round((rate - 1.0) * 100);
    const rateStr = ratePercent >= 0 ? `+${ratePercent}%` : `${ratePercent}%`;
    const url = `/api/audio/tts?text=${encodeURIComponent(word)}&rate=${encodeURIComponent(rateStr)}`;
    let settled = false;
    const timer = setTimeout(() => {
      if (settled || myAttempt !== _ttsAttemptId) return; settled = true; clearTimeout(timer);
      // 超时即弃：不清 src 的话后台还在拉这份 MP3，加载完成会突然出声，
      // 打断用户当下的操作（下一次 playWord 之前没有任何东西会停它）。
      try { _ttsAudio.pause(); _ttsAudio.removeAttribute('src'); } catch (e) {}
      innerRes(finalResolve({ ok: false, engine: 'server', error: "timeout" }));
    }, 3000);
    _ttsAudio.onerror = () => {
      if (settled || myAttempt !== _ttsAttemptId) return; settled = true; clearTimeout(timer);
      console.warn("[TTS] server audio-error: src=" + _ttsAudio.src);
      innerRes(finalResolve({ ok: false, engine: 'server', error: "audio-error" }));
    };
    _ttsAudio.onplaying = () => {
      if (settled || myAttempt !== _ttsAttemptId) return; settled = true; clearTimeout(timer);
      innerRes(finalResolve({ ok: true, engine: 'server' }));
    };
    // 语速已在服务端烘焙进音频（rate 参数），浏览器侧不再二次变速
    _ttsAudio.playbackRate = 1.0;
    _ttsAudio.src = url;
    // 同步调用 play()，保留用户手势上下文（与 tryOnline 同一套规避策略）
    const p = _ttsAudio.play();
    if (p && typeof p.then === 'function') {
      p.catch((err) => {
        if (settled || myAttempt !== _ttsAttemptId) return; settled = true; clearTimeout(timer);
        console.warn("[TTS] server play-rejected:", err && err.name);
        innerRes(finalResolve({ ok: false, engine: 'server', error: "play-rejected" }));
      });
    }
  });

  // ---- 分支 A：Web Speech 强制（engine=speech），或 engine=auto 无在线路径 ----
  const trySpeech = (reasonIfFallback) => new Promise((innerRes) => {
    if (typeof speechSynthesis === 'undefined' || typeof SpeechSynthesisUtterance === 'undefined') {
      return innerRes(finalResolve({ ok: false, engine: 'speech', error: "speechSynthesis-unavailable:" + reasonIfFallback }));
    }
    // pick voice：先尝试缓存 _ttsVoice；若空，立即同步 getVoices() 重试一次
    // （Android Chrome 首次启动 voiceschanged 事件可能尚未触发，但 getVoices() 已能返回）
    let voice = _ttsVoice;
    if (!voice) {
      try { voice = pickDeVoice(); _ttsVoice = voice; } catch (e) { voice = null; }
    }
    if (!voice) {
      return innerRes(finalResolve({ ok: false, engine: 'speech', error: "no-de-voice" }));
    }
    try {
      const u = new SpeechSynthesisUtterance(word);
      u.lang = voice.lang || 'de-DE';
      u.voice = voice;
      u.rate = Math.max(0.5, Math.min(2, rate));
      u.pitch = 1;
      u.volume = 1;
      const start = Date.now();
      let settled = false;
      u.onend = () => { if (settled) return; settled = true; innerRes(finalResolve({ ok: true, engine: 'speech', duration: Date.now() - start })); };
      u.onerror = (ev) => {
        if (settled) return; settled = true;
        const err = ev.error || '';
        // interrupted/canceled = 另一次 playWord 的 cancel() 打断了本次，
        // 是正常的播放切换，不是真正的失败；映射成 superseded 让调用方静默处理。
        const mapped = (err === 'interrupted' || err === 'canceled') ? 'superseded' : err;
        innerRes(finalResolve({ ok: false, engine: 'speech', error: "utterance-error:" + mapped }));
      };
      // 保险：12 秒兜底超时，防止 speech 不回调 onend
      setTimeout(() => { if (!settled) { settled = true; try { speechSynthesis.cancel(); } catch (e) {} innerRes(finalResolve({ ok: true, engine: 'speech', error: "timeout-fallback" })); } }, 12000);
      speechSynthesis.speak(u);
    } catch (e) {
      return innerRes(finalResolve({ ok: false, engine: 'speech', error: "exception:" + String(e && e.message || e) }));
    }
  });

  // ---- 分支 B：在线（HTMLAudioElement）----
  // 移动端 Chrome autoplay 策略：play() 必须在用户手势同步栈内调用，
  // 不能在 oncanplay 异步回调里调，否则 NotAllowedError 拦截。
  // 修复策略：设 src 后立即同步调用 play()，浏览器会自动等待加载完再播；
  // 加载失败/超时由 onerror/timeout 处理。
  // 多源策略：有道 API 已下线（500），改用多源顺序尝试，4 秒换下一个源
  const TTS_SOURCES = [
    // 1. 百度翻译 TTS（国内最稳定，多年可用）
    word => `https://fanyi.baidu.com/gettts?lan=de&text=${encodeURIComponent(word)}&spd=3&source=web`,
    // 2. Google Translate TTS（境外/翻墙环境最稳）
    word => `https://translate.google.com/translate_tts?ie=UTF-8&q=${encodeURIComponent(word)}&tl=de&client=tw-ob`,
    // 3. 有道（保留兜底，万一恢复）
    word => `https://dict.youdao.com/dictvoice?audio=${encodeURIComponent(word)}&type=3`,
  ];
  const tryOnline = () => new Promise((innerRes) => {
    if (!_ttsAudio) {
      return innerRes({ ok: false, engine: 'online', error: "no-audio-elem" });
    }
    let settled = false;
    let tm = null;
    let sourceIdx = 0;
    const cleanup = () => {
      if (tm) { clearTimeout(tm); tm = null; }
    };
    const trySource = () => {
      if (settled) return;
      if (sourceIdx >= TTS_SOURCES.length) {
        if (settled) return; settled = true; cleanup();
        console.warn("[TTS] all online sources failed");
        innerRes({ ok: false, engine: 'online', error: "all-sources-failed" });
        return;
      }
      const url = TTS_SOURCES[sourceIdx](word);
      console.log("[TTS] trying source", sourceIdx, url);
      try {
        _ttsAudio.onerror = () => {
          // 当前源失败，尝试下一个（stale attempt 直接退出）
          if (myAttempt !== _ttsAttemptId) return;
          sourceIdx++;
          trySource();
        };
        _ttsAudio.onplaying = () => {
          if (settled || myAttempt !== _ttsAttemptId) return; settled = true; cleanup();
          innerRes(finalResolve({ ok: true, engine: 'online' }));
        };
        // 4 秒超时：playing 不触发就换源
        if (tm) clearTimeout(tm);
        tm = setTimeout(() => {
          if (settled || myAttempt !== _ttsAttemptId) return;
          sourceIdx++;
          trySource();
        }, 4000);
        _ttsAudio.preload = "auto";
        _ttsAudio.playbackRate = Math.max(0.5, Math.min(2, rate));
        _ttsAudio.src = url;
        // 同步调用 play()，保留 click 手势上下文
        const p = _ttsAudio.play();
        if (p && typeof p.then === 'function') {
          p.catch((err) => {
            if (settled || myAttempt !== _ttsAttemptId) return;
            sourceIdx++;
            trySource();
          });
        }
      } catch (e) {
        if (settled) return;
        sourceIdx++;
        trySource();
      }
    };
    trySource();
  });

  // ---- 主调用链（server TTS 优先 → 在线 → Web Speech） ----
  const needServer = engine === 'server' || engine === 'auto';
  const needOnline = engine === 'online' || engine === 'auto';
  const needSpeech = engine === 'speech' || engine === 'auto';

  if (needServer) {
    return tryServer().then((r) => {
      if (r.ok) return finalResolve(r);
      if (engine === 'server') return finalResolve(r);
      // auto：server 失败 → 原有在线链 → Web Speech 兜底
      if (needOnline) {
        return tryOnline().then((r2) => {
          if (r2.ok) return finalResolve(r2);
          if (!needSpeech) return finalResolve(r2);
          return trySpeech("online-failed:" + (r2.error || ''));
        });
      }
      return trySpeech("server-failed:" + (r.error || ''));
    });
  } else if (needOnline) {
    return tryOnline().then((r) => {
      if (r.ok) return finalResolve(r);
      if (engine === 'online' || !needSpeech) return finalResolve(r);
      return trySpeech("online-failed:" + (r.error || ''));
    });
  } else {
    return trySpeech("engine-speech");
  }
}
