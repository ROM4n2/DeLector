/**
 * wb-queue.js —— 复习队列构建 / 调度族（C7 Task 5 · 块 6：wbqueue）
 *
 * 本文件内容从 static/german/workbench.html 的内联脚本**逐字节**搬出，未改写一个字符
 * （八段片段的 sha256 与原文逐段相等，见本次提交说明）：
 *   1) manualExtraIds —— 手动追加豁免集，连同上方「与 revQueue 同生命周期」的说明注释；
 *   2) 队列构建 / 调度五件：整队重建、切 scope 时的尾部静默手术、配额重算、
 *      错题本智能推送、队列信息文案 —— 各连同其上方说明注释；
 *   3) 两个队列追加入口：额外复习已学卡、额外学新词（连同上方「额外学新词……」注释）。
 * 搬动前后唯一新增的字节是本段说明性文件头、HTML 侧两处指针注释与一处 <script src>
 * 引入说明（含加载序理由）。
 *
 * 范围判据（为什么是这八个，而不是「所有碰 revQueue 的声明」）：
 *   · 收进来的都是**队列的构建 / 裁剪 / 追加**声明：它们决定「今天这一队有哪些词、
 *     什么顺序、受不受配额管」，且自己不碰 DOM 元素（最多转手调 renderReview()）；
 *   · 刻意**没收** revQueue / revIdx / flipped / ratedCount / queueDay ——
 *     那是会话内存态，与渲染/评价 handler（renderReview / showCard / flipCard /
 *     doRate / browsePrev / browseNext）强耦合，归下一块（render）一起看才读得通；
 *     本文件对这些绑定只有**运行期**引用（函数被调用时才读），故排在它们之前不成问题；
 *   · 也**没收** renderReview 与自测渲染族（quiz* / card*）—— 那是第 2 小步的事。
 *
 * 引入方式：入口页用**普通** <script src> 加载，全序为
 *     wb-seed-data.js → wb-idb.js → wb-tts.js → wb-views.js → wb-sync.js → wb-scope.js
 *     → wb-queue.js → 主内联脚本
 * 刻意不用 ES Module：Android/WebView 的模块加载语义未真机验证，必须保留整体回退成
 * 内联脚本的能力。本文件零 import / export。
 *
 * 为什么排在 wb-scope.js 之后、主内联脚本之前：本文件是**纯声明**，加载期一行都不执行
 * （豁免集只建一个 Set 字面量），排位只看「谁提供它运行期读的声明」——判定链
 * （inScopeWord / wordById）在 wb-scope.js，shuffle / logToday / endToday / S 在更早的
 * 模块或主内联脚本里；反向依赖（主内联脚本的 renderReview、顶栏 handlers、启动块的
 * backfillCoreWords）全是运行期的。故位置只表达阅读顺序：紧跟判定链，读作
 * 「队列按判定结果排」。
 *
 * 跨文件依赖（全部在**运行期**解析；顶层 let/const/function 落在同一全局词法环境）：
 *   S / revQueue / revIdx / queueDay —— 主内联脚本的状态声明；
 *   wordById / inScopeWord —— wb-scope.js；
 *   shuffle / logToday / endToday / toast —— 主内联脚本与更早模块；
 *   renderReview —— 主内联脚本（渲染层，本块只转手调它）。
 */

/* 手动追加（extraNewWords）的超配额新词 id：renormalizeQueueTail 裁剪时豁免它们。
 * 内存态，与 revQueue 同生命周期：revQueue 不持久化、刷新即重建，且
 * buildReviewQueue() 整队重建时本集合一并清空（见其函数体首行），故无需持久化。
 * 声明必须排在 buildReviewQueue 之前 —— const 有 TDZ，声明在使用之后的话，
 * 将来有人把 buildReviewQueue() 挪到模块顶层更早处调用就会抛 ReferenceError。 */
const manualExtraIds = new Set();

function buildReviewQueue() {
  /* 整队重建 = 旧队列作废，手动追加的豁免登记跟着作废。不清的话：标签页跨夜不关，
   * 昨天手动追加、今天仍未学的词一旦被排进新队列就仍被当 pinned，
   * 逃过 dailyNew 调低时的裁剪（docs/plans/workbench-scope-control-and-live-settings.md · Task 6）。 */
  manualExtraIds.clear();
  const now = Date.now(), eod = endToday();
  /* 手动标「已稳固」的卡不参与排期 */
  const dueIds = Object.keys(S.cards)
    .filter(id => {
      const w = wordById(id);
      return S.cards[id].reps > 0 && !S.cards[id].manual && S.cards[id].due <= eod && w && inScopeWord(w);
    })
    .sort((a, b) => S.cards[a].due - S.cards[b].due);
  const today = logToday();
  const newQuota = Math.max(0, S.settings.dailyNew - (today.nw || 0));
  const newIds = [];
  if (newQuota > 0) {
    const seen = new Set(dueIds);
    let pool = S.words.filter(w => !S.cards[w.id] && !seen.has(w.id) && inScopeWord(w)).map(w => w.id);
    if (S.settings.newOrder !== "seed") pool = shuffle(pool);  // 乱序引入，防顺序记忆依赖
    newIds.push.apply(newIds, pool.slice(0, newQuota));
  }
  revQueue = dueIds.concat(newIds);
  revIdx = 0;
  // F4 · 错题本智能推送：把 5 个高错题词插入队列头部（去重）
  injectWrongWords(5);
}

/* 复习中途切 scope：只静默剔除 revIdx 之后的越界词。
 * revIdx 及之前是已评价历史（「上一张」要能回看），revIdx / ratedCount / queueDay 一律不动；
 * 因为队头始终保留，revIdx < revQueue.length 恒成立，renderReview 不会误判本轮结束而重建。 */
function refilterReviewQueueForScope() {
  const tail = revQueue.slice(revIdx + 1).filter(id => {
    const w = wordById(id);
    return inScopeWord(w);
  });
  revQueue = revQueue.slice(0, revIdx + 1).concat(tail);
  if (curView === "review") renderReview();
}

/* 尾部重算：只动 revIdx 之后的未评部分，已复习的一律不动、位置不丢。
 * today.nw 只计已评新词，队列中未评新词不计入，故重算不重复扣减配额。
 * revIdx >= revQueue.length（今日刷完）时 slice(0, revIdx+1) 即整队、tail 为空，
 * 补进来的词正好落在 revIdx 位置 —— 不需要特判。 */
function renormalizeQueueTail() {
  const head = revQueue.slice(0, revIdx + 1);
  const tail = revQueue.slice(revIdx + 1);
  const keptDue = tail.filter(id => S.cards[id]);              // 到期卡不受配额管
  const newInTail = tail.filter(id => !S.cards[id]);
  const pinned = newInTail.filter(id => manualExtraIds.has(id)); // 手动追加豁免
  const normal = newInTail.filter(id => !manualExtraIds.has(id));
  const quota = Math.max(0, S.settings.dailyNew - (logToday().nw || 0));
  let next = normal.slice(0, quota);                            // 调低则裁
  if (next.length < quota) {                                    // 调高则补
    const inQ = new Set(revQueue);
    let pool = S.words.filter(w => !S.cards[w.id] && !inQ.has(w.id) && inScopeWord(w)).map(w => w.id);
    if (S.settings.newOrder !== "seed") pool = shuffle(pool);
    next = next.concat(pool.slice(0, quota - next.length));
  }
  revQueue = head.concat(keptDue, next, pinned);
  if (curView === "review") renderReview();
}

/* F4 · 错题本智能推送：根据 wrong.n（错次）+ 最近 due 时间，挑 N 个高错题词插到队列头 */
function injectWrongWords(n) {
  if (!S.wrong || !revQueue) return;
  const seen = new Set(revQueue);
  const candidates = Object.entries(S.wrong)
    .filter(([id, w]) => {
      if (!w || w.n <= 0 || seen.has(id)) return false;
      const word = wordById(id);
      return inScopeWord(word);
    })
    .map(([id, w]) => ({ id, n: w.n, lastT: w.t || 0 }))
    .sort((a, b) => b.n - a.n || a.lastT - b.lastT)  // 错次高的优先；同错次取更早的
    .slice(0, n);
  for (let i = candidates.length - 1; i >= 0; i--) {
    revQueue.unshift(candidates[i].id);
  }
}

function queueInfoText() {
  const eod = endToday();
  let dueN = 0, overdue = 0, newN = 0;
  for (const id of revQueue) {
    const c = S.cards[id];
    if (!c) newN++;
    else if (c.due <= eod) { dueN++; if (c.due < Date.now()) overdue++; }
  }
  return "今日到期 " + dueN + (overdue ? "（含逾期 " + overdue + "）" : "") + " · 新词 " + newN;
}

/* C7 Task 5 · 块 6：两个队列追加入口（extraPractice / extraNewWords）与上面五件
 * 同住本模块 —— 它们都只往 revQueue 追加并登记豁免，属同一条队列构建链；
 * 原文中间隔着的 renderReview / showCard / doRate / browsePrev / browseNext 是渲染族，
 * 按块纪律留在 workbench.html 由下一块处理。 */

function extraPractice() {
  const inQueue = new Set(revQueue);
  const pool = shuffle(S.words.filter(w => S.cards[w.id] && S.cards[w.id].reps > 0 && !inQueue.has(w.id) && inScopeWord(w)))
    .slice(0, 20).map(w => w.id);
  if (!pool.length) { toast("没有可额外复习的已学卡片"); return; }
  revQueue = revQueue.concat(pool);
  toast("已追加 " + pool.length + " 张已学卡片");
  renderReview();
}

/* 额外学新词：按当前新词顺序设置取未学词追加进今日队列；
   首评会计入今日 nw，占明日常规配额，总学习量守恒 */
function extraNewWords() {
  if (queueDay !== todayStr()) { buildReviewQueue(); queueDay = todayStr(); }
  const inQueue = new Set(revQueue);
  const pool = S.words.filter(w => !S.cards[w.id] && !inQueue.has(w.id) && inScopeWord(w));
  const ordered = S.settings.newOrder === "seed" ? pool : shuffle(pool);
  const ids = ordered.slice(0, 20).map(w => w.id);
  if (!ids.length) { toast("没有未学的新词了 🎉"); return; }
  ids.forEach(id => manualExtraIds.add(id));
  revQueue = revQueue.concat(ids);
  toast("已追加 " + ids.length + " 个新词（计入今日配额）");
  renderReview();
}
