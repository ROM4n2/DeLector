/**
 * wb-sync.js —— 背词进度 server 镜像同步（C7 Task 5 · 块 4：wbsync）
 *
 * 本文件内容从 static/german/workbench.html 的内联脚本**逐字节**搬出，未改写一个字符
 * （三段片段的 sha256 与原文逐段相等，见本次提交说明）：
 *   1) `const wbsync = (() => { … })();` —— 端点/防抖/轮询常量、稳定字符串化 stable()、
 *      snapshot()、Stage A 配对（loadPair/setPair/clearPair/pairInfo/revokePair）、
 *      Stage B WebRTC DataChannel（rtc* 全套与 autoSync）、pushNow()/push()/pull()/boot()/
 *      init() 与对外返回对象；连同上方「F3 · 背词进度 server 镜像同步」分节 banner；
 *   2) `normHw()` —— 归一词头（applyMerge 的二级索引 key）；
 *   3) `applyMerge()` —— 合并导入算法（后台轮询 / WebRTC / 文件导入共用同一份）；
 *   4) `migrateSeedIdAliases()` —— 已下架 id 的进度归并（连同其上方两段说明注释）。
 * 搬动前后唯一新增的字节是本段说明性文件头（片段之间只加了分隔空行）。
 *
 * 范围判据（为什么是这四个，而不是「所有 wb* 声明」）：
 *   · 收进来的都是**进度镜像这条链**上的声明：推送（saveXxx → wbsync.push）、拉取/轮询
 *     （pull → applyMerge）、以及被同步与导入共用的合并/归一口径；
 *   · 刻意**没收** wbPair* 八个函数（wbPairStatusMsg / wbPairPingRemote / wbPairCopyKey /
 *     wbPairSavePair / wbPairClearPair / wbPairHostHintMsg / wbPairRevoke / wbPairLanInfo）——
 *     它们是「设置 → LAN 同步」面板的 DOM 接线，与本模块只有 wbsync.pair.* 这一条调用边，
 *     归配对 UI 块；本文件只提供它们调用的 API；
 *   · 也**没收** saveCards / saveLog / saveWrong / saveSettings（存储层，留在主内联脚本）、
 *     saveWords（存储层，住 wb-idb.js）—— 它们是调用方，不是同步实现。
 *
 * 引入方式：入口页用**普通** <script src> 加载，全序为
 *     wb-seed-data.js → wb-idb.js → wb-tts.js → wb-views.js → wb-sync.js → 主内联脚本
 * 刻意不用 ES Module：Android/WebView 的模块加载语义未真机验证（计划 Fog of War
 * Unknown 2），必须保留整体回退成内联脚本的能力。本文件零 import / export。
 *
 * 为什么排在 views 之后（紧邻主内联脚本）：本文件是**纯声明**，加载期一行都不执行
 * （IIFE 只建闭包：不碰 fetch / localStorage / DOM），但它引用的声明面最宽 ——
 *   K / S / DEFAULT_SETTINGS / SEED_ID_ALIASES（wb-seed-data.js）
 *   saveWords / idbHydrate（wb-idb.js）
 *   renderHeaderBadge / showView（wb-views.js）
 *   saveCards / saveLog / saveWrong / saveSettings / normalizeWord / applyTheme / toast /
 *   renderReview / A1_BOOT_PENDING（主内联脚本）
 * 排在队尾 = 与「谁提供这些声明」的阅读顺序一致；启动期唯一入口 wbsync.init() 写在主
 * 内联脚本的启动 async IIFE 里（IDB hydrate 之后），此时全部声明已就绪。
 *
 * 跨文件依赖（全部在**运行期**解析；顶层 let/const/function 落在同一全局词法环境）：
 *   wbsync.push() ← saveCards/saveLog/saveWrong/saveSettings（主内联脚本）、
 *                   saveWords（wb-idb.js）
 *   wbsync.init() ← 主内联脚本启动 async IIFE（晚于 idbHydrate()）
 *   wbsync.pair.* / wbsync.snapshot() / wbsync.rtc.* ← wbPair* 面板、__wb 调试出口
 * => 这些声明只能在主内联脚本解析完成之后被调用（启动序 / UI / 定时器）。
 *    任何「在加载期调用 wbsync.push / applyMerge / migrateSeedIdAliases」的写法都会撞上
 *    TDZ 或 ReferenceError，不要加。
 */

/* ======================================================================
 * F3 · 背词进度 server 镜像同步（wbsync）
 *  - 本地为准（local-first）：localStorage/IDB 的键永不因同步被删改，
 *    远端只是「最近一台设备推上来的全量镜像」。
 *  - 存储层 5 个 saveXxx() 末尾都挂 wbsync.push()：本地一落盘 → 800ms 防抖
 *    → PUT /api/wb/state（带 X-WB-Key）。
 *  - 启动（IDB hydrate 完成后）+ 每 5s 轮询 GET /api/wb/state，与本地做
 *    stable-diff：真有差异才 applyMerge（复用合并导入算法），无差异不碰 UI。
 *  - key 只在本机可取（/api/wb/state/key 有 127.0.0.1 闸）；file:// / 离线 /
 *    未启动 server 一律静默禁用，数据仍只落本地，功能不受影响。
 * ==================================================================== */
const wbsync = (() => {
  const ENDPOINT = "/api/wb/state";
  const PUSH_DEBOUNCE_MS = 800;   // 复习连击时合并推送，省请求
  const POLL_MS = 5000;
  let _key = null;                // 同步 key（本机取一次）
  let _enabled = false;
  let _pushTimer = null;
  let _pollTimer = null;
  let _busy = false;
  let _pair = null;               // 配对远端 {host, key}，Stage A（见 K.pair）

  /* 稳定字符串化：对象键字典序、数组保序。同一份语义内容在不同设备上
   * JSON 键插入顺序可能不同，直接 JSON.stringify 会假 diff → 反复空合并
   * → toast + showView("review") 打断当前视图。 */
  function stable(o) {
    return JSON.stringify(o, (k, v) => {
      if (v && typeof v === "object" && !Array.isArray(v)) {
        return Object.keys(v).sort().reduce((acc, kk) => { acc[kk] = v[kk]; return acc; }, {});
      }
      return v;
    });
  }
  function snapshot() {
    return { words: S.words, cards: S.cards, log: S.log, wrong: S.wrong, settings: S.settings };
  }
  /* Stage A 配对远端：localStorage 存 {host, key}。命中后推/拉都指向
   * http://<host>/api/wb/state（host 可含端口），不再依赖本机 /key。
   * 读失败（file:// 无 localStorage / 解析坏 / 字段缺失）一律当未配对，静默。 */
  function loadPair() {
    try {
      const raw = localStorage.getItem(K.pair);
      if (raw) {
        _pair = JSON.parse(raw);
        if (!_pair || !_pair.host || !_pair.key) _pair = null;
      }
    } catch (e) { _pair = null; }
  }
  function remoteEndpoint() {
    return _pair && _pair.host ? "http://" + _pair.host + ENDPOINT : ENDPOINT;
  }
  function setPair(host, key) {
    host = String(host || "").trim();
    key = String(key || "").trim();
    if (!host || !key) return false;
    _pair = { host: host, key: key, ts: Date.now() };
    try { localStorage.setItem(K.pair, JSON.stringify(_pair)); } catch (e) { /* 存不下就本次内存有效 */ }
    _enabled = true;
    _key = key;
    return true;
  }
  function clearPair() {
    _pair = null;
    _key = null;
    try { localStorage.removeItem(K.pair); } catch (e) {}
  }
  function pairInfo() {
    return _pair ? { host: _pair.host, key: _pair.key, ts: _pair.ts } : null;
  }
  /* 撤销配对（Stage B M2）：让「本页所在这台机器」重新生成同步密钥，旧 key 立即 403。
   * POST /api/wb/state/key 有 _require_localhost 闸，手机上调必然 403 —— 手机侧要解除
   * 配对走 pair.clear()，不能用 revoke。
   * 成功返回新 key（本机改用它继续推送，否则会被自己作废的 key 卡死），失败返回 null。 */
  async function revokePair() {
    let res = null;
    try {
      res = await fetch(ENDPOINT + "/key", { method: "POST", cache: "no-store" });
    } catch (e) { return null; }
    if (!res || !res.ok) return null;
    let newKey = null;
    try { newKey = ((await res.json()) || {}).key || null; } catch (e) { return null; }
    clearPair();
    if (!newKey) return null;
    _key = newKey;
    return newKey;
  }

  /* ── Stage B M3：WebRTC DataChannel ──────────────────────────────────────
   * 信令走 /api/wb/rtc/signal（routes_rtc，按配对密钥建邮箱），两端靠同一把 key
   * 互相发现。角色由「是否已配对」决定：已配对到远端的一侧发起 offer，宿主侧应答
   * —— 不必额外协商，也不会两边同时 offer 打架。
   * 信封沿用 HTTP PUT 的 {payload:{...}} 形状：两种通道共一套契约，少一处不一致。 */
  const RTC_ENDPOINT = "/api/wb/rtc/signal";
  const RTC_CHANNEL = "wb-sync";
  const RTC_POLL_MS = 2000;
  const RTC_RETRY_MS = 3000;   // 断线重建去抖：ICE 抖动时别一秒建好几次
  const RTC_MAX_FAILS = 3;     // 连续失败上限：到点降级到 Stage A 的 HTTP 轮询
  let _rtc = null;            // RTCPeerConnection
  let _chan = null;           // DataChannel
  let _rtcId = null;          // 本端会话 id（信令 sender；只用 [0-9a-z-]，查询串免转义）
  let _rtcCursor = 0;         // 信令游标：只处理游标之后的消息，避免重放整个握手
  let _rtcPoll = null;
  let _rtcAnswered = false;
  let _rtcFails = 0;          // 连续失败次数：到上限就降级，不无限重试
  let _rtcDegraded = false;   // 已降级：WebRTC 不再重试，交给 Stage A HTTP 轮询兜底
  let _rtcRetryTimer = null;
  let _pullFails = 0;    // HTTP pull 连续失败：指数退避（5s→30s cap），别热循环打 server
  let _pullSkip = 0;     // 退避中跳过的轮询 tick 数

  function rtcSupported() {
    return typeof RTCPeerConnection !== "undefined";
  }
  function rtcId() {
    if (!_rtcId) _rtcId = String(Date.now()) + "-" + Math.random().toString(36).slice(2, 10);
    return _rtcId;
  }
  function remoteRtcEndpoint() {
    return _pair && _pair.host ? "http://" + _pair.host + RTC_ENDPOINT : RTC_ENDPOINT;
  }
  async function rtcPost(type, payload) {
    try {
      await fetch(remoteRtcEndpoint(), {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-WB-Key": _key },
        body: JSON.stringify({ client: rtcId(), type: type, payload: payload }),
        cache: "no-store",
      });
      return true;
    } catch (e) { return false; }
  }
  function rtcSendEnvelope(env) {
    if (_chan && _chan.send) _chan.send(JSON.stringify(env));
  }
  function rtcOnOpen() {
    rtcSendEnvelope({ payload: snapshot() });
  }
  function rtcOnMessage(ev) {
    let env = null;
    try { env = JSON.parse(ev.data); } catch (e) { return; }
    if (!env || !env.payload) return;
    applyMerge(env.payload, { silent: true });   // 后台同步：静默合并，不弹窗、不切视图
    renderReview();
    renderHeaderBadge();
  }
  function rtcOnIce(ev) {
    if (!ev || !ev.candidate) return;
    rtcPost("candidate", ev.candidate.toJSON ? ev.candidate.toJSON() : ev.candidate);
  }
  async function rtcHandle(m) {
    if (!_rtc) return;
    if (m.type === "offer") {
      if (_rtcAnswered) return;
      await _rtc.setRemoteDescription(m.payload);
      const answer = await _rtc.createAnswer();
      await _rtc.setLocalDescription(answer);
      _rtcAnswered = true;
      await rtcPost("answer", answer);
      return;
    }
    if (m.type === "answer") {
      if (_rtcAnswered) return;
      await _rtc.setRemoteDescription(m.payload);
      _rtcAnswered = true;
      return;
    }
    if (m.type === "candidate" && _rtc.addIceCandidate) {
      await _rtc.addIceCandidate(m.payload);
    }
  }
  async function rtcPoll() {
    if (!_key) return;
    let res = null;
    try {
      res = await fetch(remoteRtcEndpoint() + "?client=" + rtcId() + "&after=" + _rtcCursor,
                        { headers: { "X-WB-Key": _key }, cache: "no-store" });
    } catch (e) { return; }
    if (!res || !res.ok) return;
    let data = null;
    try { data = await res.json(); } catch (e) { return; }
    _rtcCursor = data.now || _rtcCursor;
    const msgs = data.messages || [];
    for (let i = 0; i < msgs.length; i++) await rtcHandle(msgs[i]);
  }
  function rtcStartPoll() {
    if (_rtcPoll) clearInterval(_rtcPoll);
    _rtcPoll = setInterval(rtcPoll, RTC_POLL_MS);
  }
  async function rtcConnect() {
    if (!rtcSupported() || !_key) return false;
    if (_rtc) return true;                              // 已建连：幂等
    _rtcAnswered = false;
    _rtc = new RTCPeerConnection({ iceServers: [] });   // 纯局域网：不需要 STUN
    _chan = _rtc.createDataChannel(RTC_CHANNEL);
    _chan.onopen = rtcOnOpen;
    _chan.onmessage = rtcOnMessage;
    _rtc.onicecandidate = rtcOnIce;
    _rtc.onconnectionstatechange = rtcOnStateChange;
    if (_pair) {                       // 已配对到远端的一侧发起握手
      const offer = await _rtc.createOffer();
      await _rtc.setLocalDescription(offer);
      await rtcPost("offer", offer);
    }
    rtcStartPoll();
    await rtcPoll();                   // 建连阶段先拉一次，尽快收下对端的 answer
    return true;
  }
  function rtcClose() {
    if (_rtcPoll) { clearInterval(_rtcPoll); _rtcPoll = null; }
    if (_chan && _chan.close) _chan.close();
    if (_rtc && _rtc.close) _rtc.close();
    _chan = null;
    _rtc = null;
    _rtcAnswered = false;
  }
  function rtcOnStateChange() {
    if (!_rtc) return;
    const st = _rtc.connectionState || _rtc.iceConnectionState || "";
    if (st === "connected" || st === "completed") { _rtcFails = 0; return; }
    if (st !== "failed" && st !== "closed" && st !== "disconnected") return;
    // disconnected 是瞬态（如信号弱/ICE 重协商），不累计失败次数，避免误降级
    rtcScheduleRetry(st === "disconnected");
  }
  function rtcScheduleRetry(skipCount) {
    if (_rtcDegraded || _rtcRetryTimer) return;   // 去抖：一次断线只排一次重建
    if (!skipCount) _rtcFails += 1;
    if (_rtcFails > RTC_MAX_FAILS) {              // 到上限：降级并停手，别空转打服务端
      _rtcDegraded = true;
      rtcClose();
      return;
    }
    _rtcRetryTimer = setTimeout(function () {
      _rtcRetryTimer = null;
      rtcClose();
      rtcConnect();
    }, RTC_RETRY_MS);
  }
  function rtcDegraded() {
    return _rtcDegraded;
  }
  /* 编排入口：优先 WebRTC；不可用/建不起来就降级，Stage A 的 HTTP 轮询照常兜底。 */
  async function autoSync() {
    if (!rtcSupported()) { _rtcDegraded = true; return false; }
    const ok = await rtcConnect();
    if (!ok) { _rtcDegraded = true; return false; }
    return true;
  }

  function pushNow() {
    if (!_enabled || !_key) return;
    // 服务端契约是 {"payload": {...}}（WbStateReq），裸快照会被解析成空 payload，
    // wb_state 永远存 {}、GET 永远空 → 进度合并不进来（2026-09-02 线上事故根因）。
    fetch(remoteEndpoint(), {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-WB-Key": _key },
      body: JSON.stringify({ payload: snapshot() }),
    }).catch(() => { /* server 不可达：本地数据已安全，静默 */ });
  }
  function push() {
    if (!_enabled || !_key) return;
    clearTimeout(_pushTimer);
    _pushTimer = setTimeout(pushNow, PUSH_DEBOUNCE_MS);
  }
  async function pull() {
    // GET /api/wb/state 对局域网开放、无需 key（server.py:1419）——只有推送才要 key。
    // 拿不到 key（手机/平板是远端 IP，/key 被 _require_localhost 限制返回 403）也照常拉取，
    // 否则跨设备进度永远合不进来（2026-09-03 事故：手机看不到背词进度）。
    if (!_enabled || _busy) return;
    if (_pullSkip > 0) { _pullSkip -= 1; return; }   // 失败退避中：本 tick 不发请求
    _busy = true;
    let failed = false;
    try {
      const r = await fetch(remoteEndpoint(), { cache: "no-store" });
      if (!r.ok) { failed = true; return; }
      const remote = await r.json();
      if (!remote || typeof remote !== "object") { failed = true; return; }
      if (Object.keys(remote).length === 0) { pushNow(); return; }  // server 空 → 拿本机当种子
      if (stable(remote) === stable(snapshot())) return;            // 无实质差异，跳过
      applyMerge(remote, { silent: true });                         // 复用合并导入算法（后台轮询静默）
      renderReview();
      renderHeaderBadge();
    } catch (e) { failed = true; }   // 离线/未启动 server：静默，但计入退避
    finally {
      _busy = false;
      if (failed) {                    // 指数退避：跳过 1,2,4,6… 个 tick（≈5s→30s cap）
        _pullFails += 1;
        _pullSkip = Math.min(2 ** (_pullFails - 1), 6);
      } else if (_pullFails) {
        _pullFails = 0;
      }
    }
  }
  async function boot() {
    // 配对远端（Stage A）：localStorage 有 wb.pair.v1 就直接用它的 host+key，
    // 推/拉都走 http://<host>/api/wb/state，不再取本机 /key。
    loadPair();
    if (_pair) {
      _key = _pair.key;
    } else {
      // 拉取（GET /api/wb/state）对局域网开放、无需 key；只有「推送」才需要 key。
      // 因此即便拿不到 key（手机/平板是远端 IP，/key 被 _require_localhost 限制返回 403），
      // 也照常启用拉取，让跨设备进度能自动合进来（2026-09-03 手机看不到背词进度根因）。
      try {
        const kr = await fetch(ENDPOINT + "/key", { cache: "no-store" });
        if (kr.ok) _key = (await kr.json()).key;   // 拿到则同时启用推送，拿不到则仅拉取模式
      } catch (e) { /* 离线 / file://：跳过 key，进入仅拉取模式 */ }
    }
    _enabled = true;
    try {
      await pull();                       // 启动即拉一次（远端无 key 时不推送种子）
      document.addEventListener("visibilitychange", () => {
        if (document.hidden) pushNow();   // 切走前推一把（有 key 才生效）
        else pull();                      // 回前台拉最新
      });
      window.addEventListener("beforeunload", () => pushNow());
      _pollTimer = setInterval(pull, POLL_MS);
    } catch (e) { /* 拉取失败：静默 */ }
    // HTTP 轮询已在上面跑起来（兜底），再试着升级到 WebRTC；失败自动降级回轮询。
    try { await autoSync(); } catch (e) { _rtcDegraded = true; }
  }
  function init() { boot(); }
  return { init: init, push: push, pushNow: pushNow, pull: pull,
    enabled: () => _enabled, snapshot: snapshot,
    pairInfo: pairInfo, autoSync: autoSync,
    pair: { set: setPair, clear: clearPair, info: pairInfo, revoke: revokePair },
    rtc: { connect: rtcConnect, supported: rtcSupported, send: rtcSendEnvelope, close: rtcClose,
           degraded: rtcDegraded } };
})();

/** 词头归一：去掉定冠词、去首尾空白。applyMerge 的二级索引 key。
 *  大小写必须保留 —— 德语首字母大写是语义的：
 *  a1-0551 sie（她/他们）与 a1-0552 Sie（您，敬称）只差大小写且 pos 都是 Pron，
 *  小写折叠会把敬称并进第三人称，是实打实的数据丢失；
 *  essen / das Essen、leben / das Leben 也靠大小写区分。
 *  也不折入 pos —— 导入词库里有 7 个词的 pos 与种子词不一致，
 *  带上 pos 反而会让这些词漏过去重、重新变成重复条目。 */
function normHw(hw) {
  return String(hw || "").trim().replace(/^(der|die|das)\s+/, "").trim();
}
function applyMerge(data, opts) {
  opts = opts || {};
  const silent = !!opts.silent;   // 后台轮询合并（wbsync.pull）静默：不弹通知、不切视图
  /* 卡片：按最近复习时间取新 */
  const inCards = data.cards || {};
  for (const id in inCards) {
    const a = S.cards[id], b = inCards[id];
    if (!a || (b && (b.last || 0) >= (a.last || 0))) S.cards[id] = b;
  }
  /* 日志：每日各计数取较大值 */
  const inLog = data.log || {};
  for (const k in inLog) {
    const a = S.log[k] || {}, b = inLog[k] || {};
    S.log[k] = {};
    for (const f of ["rv", "good", "hard", "again", "nw", "qz", "qzOk"])
      S.log[k][f] = Math.max(a[f] || 0, b[f] || 0);
  }
  /* 错题本：取次数多者 */
  const inWrong = data.wrong || {};
  for (const id in inWrong) {
    const a = S.wrong[id], b = inWrong[id];
    if (!a || (b && b.n >= a.n)) S.wrong[id] = b;
  }
  /* 单词：wb-sync 只带自定义词；wb-full 带全部，按 up 取新。
   * 两级索引：先按 id，再按归一词头。同一个词在别的设备上是自定义词（u-008 der Wohnort）、
   * 在本机是内建核心词（core-001 der Wohnort）时，只按 id 合并会把两条同词记录并排塞进词表：
   * 两张独立 FSRS 卡、复习队列里同一个词出现两次。 */
  const inWords = data.customWords || data.words || [];
  const byId = new Map(S.words.map(w => [w.id, w]));
  const byHw = new Map();
  for (const w of S.words) {
    const k = normHw(w.hw);
    if (k && !byHw.has(k)) byHw.set(k, w);
  }
  let added = 0, merged = 0;
  for (const w of inWords) {
    if (!w || !w.id) continue;
    const k = normHw(w.hw);
    const sameId = byId.get(w.id);
    const cur = sameId || (k ? byHw.get(k) : null);
    if (!cur) {
      /* T4-N1 承接（ADR-0011 Task 6）：远端/导入词进 S.words 前过 normalizeWord，
       * 旧形状词（缺 zh/gender/plural/cefr 键）在合并入口即归一到统一契约。
       * w.id 已验真（上方守卫），normalizeWord 不会返回 null。 */
      const nw = normalizeWord(w) || w;
      S.words.push(nw);
      byId.set(nw.id, nw);
      if (k) byHw.set(k, nw);
      added++;
      continue;
    }
    merged++;
    if ((w.up || 0) > (cur.up || 0)) {
      /* 跨 id 的同词头命中时，id / tags / custom 属于本机身份而不是词条内容：
       * id 被改写 → S.cards[原 id] 当场变孤儿卡，FSRS 进度丢失；
       * tags 被改写 → core 归属被抹掉，核心模式当场空一片；
       * custom 被改写 → 种子词开始混进 wb-sync 导出，每轮同步越滚越大。
       * 只让内容字段按 up 取新，身份字段回填成本机的。
       * id 命中时不保护 —— 那本就是同一条记录，tags 该按 up 取新。 */
      const own = sameId ? null : { id: cur.id, tags: cur.tags, custom: cur.custom };
      Object.assign(cur, w);
      if (own) Object.assign(cur, own);
    }
  }
  if (data.settings) { S.settings = Object.assign(S.settings, data.settings); saveSettings(); applyTheme(); }
  saveWords(); saveCards(); saveLog(); saveWrong();
  renderHeaderBadge();
  if (!silent) {
    toast("合并导入完成：新增 " + added + " 词、合并 " + merged + " 词，共 " + S.words.length + " 个单词");
    showView("review");
  }
}

/* 重复种子词下架后的一次性 id 归并（Task 8）。
 * 别名表（已下架 id -> 保留 id）已随种子数据抽到 static/js/wb-seed-data.js（C7 Task 4），
 * 工作台入口用普通 <script src> 先于本脚本加载它，故下方 migrateSeedIdAliases 可直接引用。
 * a1-0544 / a1-0545 与 a1-0034 / a1-0052 的 hw+pos+gloss 逐字相同（教材第 10 页与
 * 第 23 页重复收录），已从 SEED_WORDS 移除。老用户本地可能已在旧 id 上攒了 FSRS 进度，
 * 只删词不迁进度就会留下 wordById() 查不到的孤儿卡 —— 违反「进度零丢失」这条硬约束。 */

/** 把已下架 id 上的进度归并到保留 id，并清掉词表里的残留条目。
 *  - 目标位为空：整条搬过去；两边都有：保留「练得更多」的一条，另一条丢弃。
 *    取舍规则：先比 reps（复习次数），reps 相同再比 due 更晚者（间隔更长 = 记得更牢）；
 *    错题本没有 reps，按 n（错题次数）多者保留，与 applyMerge 的「取次数多者」一致。
 *  - 旧 key 无论走哪条分支都删除 —— 这是幂等性的唯一来源：跑第二次时旧 key 已不存在，
 *    三个库都不动、词表过滤长度不变，changed 恒为 false。
 *  - 与 backfillCoreWords() 同契约：仅在真发生变更时返回 true。 */
function migrateSeedIdAliases() {
  let changed = false;
  const cardWins = (a, b) => (a.reps || 0) !== (b.reps || 0)
    ? (a.reps || 0) > (b.reps || 0)
    : (a.due || 0) > (b.due || 0);
  const wrongWins = (a, b) => (a.n || 0) > (b.n || 0);
  const move = (store, oldId, newId, wins) => {
    if (!store || !Object.prototype.hasOwnProperty.call(store, oldId)) return false;
    const old = store[oldId];
    if (!Object.prototype.hasOwnProperty.call(store, newId) || wins(old, store[newId])) store[newId] = old;
    delete store[oldId];
    return true;
  };
  for (const oldId in SEED_ID_ALIASES) {
    const newId = SEED_ID_ALIASES[oldId];
    if (move(S.cards, oldId, newId, cardWins)) changed = true;
    /* S.log 按日期 key 存日计数、不按词 id，这里扫一遍纯属防御：
     * 万一某个历史版本往里写过词 id，也能顺手带走而不是留成脏 key。 */
    if (move(S.log, oldId, newId, cardWins)) changed = true;
    if (move(S.wrong, oldId, newId, wrongWins)) changed = true;
  }
  const kept = S.words.filter(w => !Object.prototype.hasOwnProperty.call(SEED_ID_ALIASES, w.id));
  if (kept.length !== S.words.length) { S.words = kept; changed = true; }
  return changed;
}
