/**
 * wb-rate.js —— 卡片渲染 / 评分回写与会话内存态（C7 Task 5 · 块 6 步骤 2：wbrate）
 *
 * 本文件内容从 static/german/workbench.html 的内联脚本**逐字节**搬出，未改写一个字符
 * （五段片段的 sha256 与原文逐段相等，见本次提交说明）：
 *   1) 复习会话态两行声明（revQueue / revIdx / flipped / ratedCount / queueDay）；
 *   2) renderReview —— 复习视图的读侧：按天建队、写进度条、落完成屏；
 *   3) showCard —— 把当前卡刷进 #cardFlip 那套 DOM，并挂卡片音频按钮；
 *   4) doRate —— 评分回写：FSRS → 卡 → 日志 → 错题本，再 `revIdx++` 翻下一张；
 *   5) renderQuizQ —— 自测单题的读侧：进度、题干、选项 / 拼写输入框。
 * 搬动前后唯一新增的字节是本段说明性文件头、上面那条会话态注释、renderQuizQ 上方的
 * 去向注释，以及 HTML 侧的三处指针注释、一段加载序说明与一处 <script src>。
 *
 * 为什么单开一个模块，而不是并进 wb-queue.js（同块合并）：
 *   · wb-queue.js 的范围判据写得很明确 —— 收进去的都是**队列的构建 / 裁剪 / 追加**，
 *     「须不碰 DOM 元素」，并明确把 revQueue / revIdx / flipped / ratedCount / queueDay
 *     与渲染族列在「刻意没收，归下一块」。并进去就得改写那段判据，模块立刻变成
 *     「数据手术 + DOM 渲染 + 评分写盘」三件事混居，后读的人再也无法靠文件边界判断
 *     「改队列逻辑该动哪」；
 *   · 本文件是那条判据的另一半：**读侧 + 会话态**。凡是「把状态刷进 DOM」或
 *     「把用户输入写回状态」的，都在这里；凡是不碰 DOM 只切数组的，都在 wb-queue.js。
 *     两块靠同一全局词法环境拼起来，边界比同文件更清楚；
 *   · renderQuizQ 更不属于队列 —— 它渲染的是自测题（quiz 会话），与 revQueue 无关。
 *
 * 引入方式：入口页用**普通** <script src> 加载，全序为
 *     wb-seed-data.js → wb-idb.js → wb-tts.js → wb-views.js → wb-sync.js → wb-scope.js
 *     → wb-queue.js → wb-rate.js → 主内联脚本
 * 刻意不用 ES Module：Android/WebView 的模块加载语义未真机验证，必须保留整体回退成
 * 内联脚本的能力。本文件零 import / export。
 *
 * 为什么排在 wb-queue.js 之后、主内联脚本之前：本文件是**纯声明**（`let` 只做初始化，
 * 一行函数体都不执行），排位只看「谁提供它运行期读的声明」—— renderReview 运行期调
 * buildReviewQueue / queueInfoText，它们在 wb-queue.js；doRate 调 fsrsReview / logToday /
 * saveCards / saveLog / addWrong，在更早的模块或主内联脚本；渲染用的是 $ / wordById /
 * S.settings 等。反向依赖（主内联脚本的启动块与顶栏 handlers 调 renderReview、flipCard
 * 改 flipped、自测块改 quiz）全是运行期的。故位置只表达阅读顺序：队列构建 → 读队渲染。
 *
 * 跨文件依赖（全部在**运行期**解析；顶层 let/const/function 落在同一全局词法环境）：
 *   S / A1_BOOT_PENDING / $ / quiz —— 主内联脚本的状态声明与 DOM 助手；
 *   buildReviewQueue / queueInfoText —— wb-queue.js；
 *   wordById —— wb-scope.js；renderHeaderBadge / renderA1BootLoading / curView —— wb-views.js；
 *   playWord / _ttsGestureUnlocked / deVoiceMissingHint —— wb-tts.js；
 *   fsrsReview / saveCards / saveLog / logToday / addWrong / toast / todayStr —— 主内联脚本；
 *   buildChoiceOptions / chooseOption / checkSpell —— 主内联脚本（自测块）。
 * 注：`quiz` 的声明在主内联脚本里、加载晚于本文件 —— 本文件只在**函数体**里碰它
 * （renderQuizQ 由 quizStart 在运行期调用），加载期不读，故不构成 TDZ 问题。
 *
 * 刻意留在 workbench.html 的（块纪律：薄 handler 与顶层**表达式**不搬）：
 *   flipCard / browsePrev / browseNext 三个函数，以及 cardFlip / .rate-btn / btnPrevCard /
 *   btnNextCard / btnExtra / btnExtraNew / btnGoQuiz 那一串 addEventListener；
 *   自测会话态与判分链（quiz / chooseOption / checkSpell / quizNext / quizSummary …）。
 */

/* 会话内存态：revQueue / revIdx / flipped / ratedCount / queueDay —— 逐字节搬自
 * workbench.html 的「复习模块」块首。与队列同生命周期的是 wb-queue.js 的
 * manualExtraIds（那边只增删集合，本处只提供队列本身）。 */
let revQueue = [];      // 词 id 队列：到期卡（按 due 升序）+ 今日新词
let revIdx = 0, flipped = false, ratedCount = 0, queueDay = null;

function renderReview() {
  /* 首装挂起（S.words 为空）：显示加载占位，不得渲染成「今日复习任务已完成」的误导态。 */
  if (A1_BOOT_PENDING) { renderA1BootLoading(); return; }
  /* 队列按天构建、会话内保持稳定：评价后不重建，保证「上一张」可回看 */
  const today = todayStr();
  if (queueDay !== today || revIdx >= revQueue.length) {
    buildReviewQueue();
    queueDay = today;
  }
  $("revInfo").textContent = queueInfoText();
  renderHeaderBadge();
  if (revIdx >= revQueue.length) {
    $("revBoard").style.display = "none";
    $("revEmpty").style.display = "";
    $("revEmptyText").textContent = ratedCount > 0
      ? "本轮完成：共评价 " + ratedCount + " 张卡片。稍后可回来继续或去自测。"
      : "今日复习任务已完成 🎉";
    $("btnExtra").disabled = !S.words.some(w => S.cards[w.id] && S.cards[w.id].reps > 0);
    $("btnExtraNew").disabled = !S.words.some(w => !S.cards[w.id]);
    return;
  }
  $("revBoard").style.display = "";
  $("revEmpty").style.display = "none";
  showCard();
}

function showCard() {
  const w = wordById(revQueue[revIdx]);
  flipped = false;
  $("cardFlip").classList.remove("flipped");
  $("cardHw").textContent = w.hw;
  $("cardIpa").textContent = w.ipa || "";
  // ---- 音频按钮：卡片 ----
  const cA = $("cardAudio");
  if (cA) {
    cA.disabled = false; cA.classList.remove("busy","voice-bad");
    cA.onclick = (ev) => {
      if (ev) ev.stopPropagation();  // 不触发卡片翻面
      cA.classList.add("busy");
      playWord(w.hw, { engine: S.settings.tts.engine, rate: S.settings.tts.rate })
        .then((r) => {
          cA.classList.remove("busy");
          if (!r.ok) {
            cA.classList.add("voice-bad");
            if (r.error === "no-de-voice") toast(deVoiceMissingHint());
            else if (r.error === "speechSynthesis-unavailable") toast("当前浏览器不支持语音播放");
            else if (r.error === "empty-word" || r.error === "tts-off"
                     || r.error === "superseded") { /* 静默：被新播放取代，不是真正的失败 */ }
            else toast("发音失败：" + r.error);
          }
        });
    };
    // autoPlay：需手势解锁（用户此前至少手动点过一次🔊）
    if (S.settings.tts.autoPlay && _ttsGestureUnlocked) {
      Promise.resolve().then(() => { if (cA && !cA.disabled) cA.click(); });
    }
  }
  $("cardPos").textContent = w.pos || "—";
  $("cardGloss").textContent = w.gloss || "—";
  const exBox = $("cardEx"); exBox.innerHTML = "";
  (w.ex || []).forEach(p => {
    const div = document.createElement("div");
    div.className = "ex";
    const de = document.createElement("div"); de.className = "de"; de.textContent = p.de || "";
    const zh = document.createElement("div"); zh.className = "zh"; zh.textContent = p.zh || "";
    if (p.de) div.appendChild(de);
    if (p.zh) div.appendChild(zh);
    if (p.de || p.zh) exBox.appendChild(div);
  });
  document.querySelectorAll(".rate-btn").forEach(b => b.disabled = true);
  $("btnPrevCard").disabled = revIdx === 0;
  $("revProgFill").style.width = (revQueue.length ? (revIdx / revQueue.length) * 100 : 0) + "%";
  $("revProgText").textContent = (revIdx + 1) + " / " + revQueue.length;
}

function doRate(g) {
  if (revIdx >= revQueue.length || !flipped) return;
  const id = revQueue[revIdx];
  const isNew = !S.cards[id] || S.cards[id].reps === 0;
  S.cards[id] = fsrsReview(S.cards[id] || null, g, Date.now(), S.settings.retention);
  saveCards();
  const t = logToday();
  t.rv++; if (isNew) t.nw++;
  if (g === 3) t.good++; else if (g === 2) t.hard++; else { t.again++; addWrong(id, "rv-again"); }
  saveLog();
  ratedCount++;
  revIdx++;
  renderHeaderBadge();
  renderReview();
}

/* renderQuizQ 原住在内联脚本的「自测模块」块内（quiz / quizType 声明之后），
 * 与 review 渲染族同为「把会话态刷进 DOM」的读侧，故一并收进本模块；
 * 自测会话态与判分链（quiz / chooseOption / checkSpell / quizNext …）仍留在原处。 */
function renderQuizQ() {
  quiz.answered = false;
  $("quizFb").innerHTML = "";
  $("btnQuizNext").style.display = "none";
  const w = wordById(quiz.ids[quiz.idx]);
  const total = quiz.ids.length;
  $("quizProgFill").style.width = (quiz.idx / total) * 100 + "%";
  $("quizProgText").textContent = (quiz.idx + 1) + " / " + total;
  const box = $("quizQBox"); box.innerHTML = "";
  if (quiz.type === "choice") {
    const dir = Math.random() < 0.5 ? "de2zh" : "zh2de";
    quiz.dir = dir;
    const opts = buildChoiceOptions(w, dir);
    quiz.opts = opts;
    $("quizQLabel").textContent = "第 " + (quiz.idx + 1) + " 题 · " + (dir === "de2zh" ? "选出正确中文释义" : "选出对应德语单词");
    const qw = document.createElement("div"); qw.className = "qword";
    if (dir === "de2zh") {
      qw.textContent = w.hw;
      if (w.ipa) { const s = document.createElement("small"); s.textContent = w.ipa; qw.appendChild(s); }
    } else qw.textContent = w.gloss;
    box.appendChild(qw);
    opts.forEach((o, i) => {
      const b = document.createElement("button");
      b.className = "qopt"; b.textContent = o.text;
      b.onclick = () => chooseOption(i);
      box.appendChild(b);
    });
  } else {
    $("quizQLabel").textContent = "第 " + (quiz.idx + 1) + " 题 · 拼写出德语原词";
    const info = document.createElement("div");
    info.className = "qword";
    info.appendChild(document.createTextNode(w.gloss || "—"));
    if (w.pos) { const s = document.createElement("small"); s.textContent = w.pos + (w.ipa ? " · " + w.ipa : ""); info.appendChild(s); }
    else if (w.ipa) { const s = document.createElement("small"); s.textContent = w.ipa; info.appendChild(s); }
    if (w.ipa) {
      const ab = document.createElement("button");
      ab.className = "audio-btn words-audio-sm"; ab.title = "听发音（拼写辅助）"; ab.textContent = "🔊";
      ab.style.marginLeft = "8px";
      ab.onclick = () => {
        ab.classList.add("busy");
        playWord(w.hw, { engine: S.settings.tts.engine, rate: S.settings.tts.rate })
          .then((r) => {
            ab.classList.remove("busy");
            if (!r.ok) {
              ab.classList.add("voice-bad");
              if (r.error === "no-de-voice") toast(deVoiceMissingHint());
            }
          });
      };
      info.appendChild(ab);
    }
    box.appendChild(info);
    const inp = document.createElement("input");
    inp.className = "spell-input"; inp.id = "spellInput";
    inp.placeholder = "输入德语单词，回车提交"; inp.autocomplete = "off";
    inp.setAttribute("autocapitalize", "off"); inp.setAttribute("spellcheck", "false");
    inp.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); checkSpell(); }
    });
    const submit = document.createElement("button");
    submit.className = "btn"; submit.id = "btnSpellOk";
    submit.style.margin = "10px auto 0"; submit.style.display = "block";
    submit.textContent = "提交答案";
    const hintP = document.createElement("p");
    hintP.className = "hint"; hintP.style.marginTop = "10px";
    hintP.textContent = "判分忽略大小写与首尾空格；ä/ö/ü/ß 可用 ae/oe/ue/ss 代替；仅差一两个字母计为基本正确。";
    box.appendChild(inp); box.appendChild(submit); box.appendChild(hintP);
    inp.focus();
  }
}
