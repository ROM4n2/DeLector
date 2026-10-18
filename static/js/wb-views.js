/**
 * wb-views.js —— 视图渲染层 + 视图路由（C7 Task 5 · 块 3：render-views）
 *
 * 本文件内容从 static/german/workbench.html 的内联脚本**逐字节**搬出，未改写一个字符
 * （八段片段的 sha256 与原文逐段相等，见本次提交说明）：
 *   1) `let curView` + `showView()`（视图路由）；
 *   2) `renderStats()`；
 *   3) `renderA1BootLoading()`，连同其上方「统一占位」三行说明；
 *   4) `renderWords()`；
 *   5) `renderSettings()`；
 *   6) `renderSnapshots()`；
 *   7) `renderPlan()`；
 *   8) `renderHeaderBadge()`。
 * 搬动前后唯一新增的字节是本段说明性文件头（片段之间只加了分隔空行）。
 *
 * 范围判据（为什么是这八个，而不是「所有 render*」）：
 *   · 收进来的都是**一个视图整块重绘**的入口：词库 / 统计 / 设置 / 计划 / 顶栏徽标 /
 *     首装占位，外加视图路由本身；
 *   · 刻意**没收** renderReview() —— 它与会话内存态 revQueue / revIdx / queueDay /
 *     ratedCount / buildReviewQueue() / queueInfoText() / showCard() 强耦合，归
 *     review-queue 块；同理 renderQuizQ() 与 quiz / quizType / buildChoiceOptions 绑定，
 *     归自测（quiz）块，一并留在 workbench.html；
 *   · renderStats 的渲染辅助 kpi / chartColors / barChartSVG / lineChartSVG 不在
 *     「render* 系列 + 视图切换」判据内，留在原地（运行期跨脚本解析，行为不变）；
 *   · 各模块的分节 banner 注释留在 workbench.html（它标的是留在原地的那个模块），
 *     只有**直接挂在本函数上**的说明（renderA1BootLoading 上方三行）随函数搬走。
 *
 * 引入方式：入口页用**普通** <script src> 加载，全序为
 *     wb-seed-data.js → wb-idb.js → wb-tts.js → wb-views.js → 主内联脚本
 * 刻意不用 ES Module：Android/WebView 的模块加载语义未真机验证（计划 Fog of War
 * Unknown 2），必须保留整体回退成内联脚本的能力。本文件零 import / export。
 *
 * 为什么排在最后（紧邻主内联脚本）：本文件是**纯声明**，加载期一行都不执行，
 * 但它引用的东西最多（$ / esc / S / wordFilters / inScopeWord / wordById / A1_BOOT_PENDING /
 * planCalc / idbListSnapshots / idbRestoreSnapshot / idbDeleteSnapshot / renderReview …），
 * 全住在前三个模块或主内联脚本里。排在队尾 = 与「谁提供这些声明」的阅读顺序一致。
 *
 * 跨文件依赖（全部在**运行期**解析；顶层 let/function 落在同一全局词法环境）：
 *   $ / esc / clamp / endToday / todayStr / wordById / wordState / wordStateKey /
 *   inScopeWord / logToday / storageUsage / letterOf / exRowHTML / kpi / chartColors /
 *   barChartSVG / lineChartSVG / planCalc / syncScopeControls / renderReview /
 *   idbListSnapshots / idbRestoreSnapshot / idbDeleteSnapshot
 * => 这些声明只能在主内联脚本解析完成之后被调用（启动序 / UI / 定时器）。
 *    任何「在加载期调用 showView / renderWords」的写法都会撞上 TDZ，不要加。
 * => 反向也成立：主内联脚本（键盘快捷键读 curView、refilterReviewQueueForScope 读
 *    curView、各处 handler 调 renderXxx）仍可直接读写本文件的顶层声明。
 *
 * 严格模式：搬出前这些代码位于主内联脚本的 "use strict" 之下，本文件不带该指令
 * （与 wb-tts.js / wb-idb.js / wb-seed-data.js 一致）。已逐条核对：本片段不依赖
 * 严格/宽松模式的任何差异（无未声明变量赋值、无裸 this、无 arguments.callee、
 * 无重复形参、无八进制字面量）。
 */

let curView = "review";
function showView(v) {
  curView = v;
  document.querySelectorAll("nav.tabs button").forEach(b =>
    b.classList.toggle("active", b.dataset.view === v));
  document.querySelectorAll(".view").forEach(s =>
    s.classList.toggle("active", s.id === "view-" + v));
  if (v === "stats") renderStats();
  if (v === "words") renderWords();
  if (v === "settings") renderSettings();
  if (v === "review") renderReview();
}

function renderStats() {
  /* KPI */
  const total = S.words.length;
  let learned = 0, solid = 0, rvAll = 0, goodAll = 0;
  for (const id in S.cards) {
    const c = S.cards[id];
    if (c.reps > 0) { learned++; rvAll += c.reps; goodAll += (c.reps - c.lapses); if (c.s >= 21 || c.manual === "solid") solid++; }
  }
  const acc = rvAll ? Math.round((goodAll / rvAll) * 100) : 0;
  /* 统计页口径保持全局总览（scope 只管复习范围），核心词单列一格进度；分母现数不写死 */
  const coreWords = S.words.filter(w => (w.tags || []).includes("core"));
  const coreLearned = coreWords.filter(w => S.cards[w.id] && S.cards[w.id].reps > 0).length;
  $("kpiRow").innerHTML =
    kpi(total, "总词数") + kpi(learned, "已学习") + kpi(solid, "已稳固") +
    kpi(coreLearned + " / " + coreWords.length, "核心词进度") +
    kpi(streakDays(), "连续学习天数", true) + kpi(acc + "%", "总体认识率");
  /* 图表 */
  const rows = last30();
  $("chartBarsBox").innerHTML = barChartSVG(rows);
  $("chartLineBox").innerHTML = lineChartSVG(rows);
  /* 字母掌握度 */
  const letters = {};
  for (const w of S.words) {
    const L = (w.letter || (w.hw[0] || "?").toUpperCase()).charAt(0).toUpperCase();
    if (!letters[L]) letters[L] = { total: 0, learn: 0, solid: 0 };
    letters[L].total++;
    const c = S.cards[w.id];
    if (c && c.reps > 0) { if (c.s >= 21 || c.manual === "solid") letters[L].solid++; else letters[L].learn++; }
  }
  const Ls = Object.keys(letters).sort();
  const cs = getComputedStyle(document.documentElement);
  const cGood = cs.getPropertyValue("--good").trim(), cHard = cs.getPropertyValue("--hard").trim(),
        cLine = cs.getPropertyValue("--line").trim(), cMuted = cs.getPropertyValue("--muted").trim();
  $("letterBarsBox").innerHTML = Ls.map(L => {
    const v = letters[L];
    const pS = (v.solid / v.total) * 100, pL = (v.learn / v.total) * 100;
    return "<div class='letter-row'><span class='lt'>" + esc(L) + "</span>" +
      "<div class='bar'><i style='width:" + pS + "%;background:" + cGood + "'></i>" +
      "<i style='width:" + pL + "%;background:" + cHard + "'></i></div>" +
      "<span class='pct' style='color:" + cMuted + "'>" + v.solid + "/" + v.total + "</span></div>";
  }).join("");

  // F4 · 渲染新增 4 个面板
  // 1) streak 徽章
  const streak = streakDays();
  const streakEl = $("streakBadge");
  if (streakEl) streakEl.textContent = streak > 0 ? (streak + " 天 🔥") : "0 天（开始学习吧）";

  // 2) 字母热图
  const hmEl = $("letterHeatmapBox");
  if (hmEl) {
    const hm = letterHeatmap();
    const letters26 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
    hmEl.innerHTML = '<div style="display:grid;grid-template-columns:repeat(13,1fr);gap:4px">' +
      letters26.map(L => {
        const v = hm[L] || { total: 0, learnt: 0, solid: 0 };
        if (v.total === 0) {
          return '<div style="aspect-ratio:1.4/1;background:var(--line);border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:11px;color:var(--muted)">' + L + '</div>';
        }
        const solidRatio = v.solid / v.total;
        const learntRatio = v.learnt / v.total;
        // 颜色深浅：稳固越多越绿
        const hue = solidRatio > 0 ? 130 : (learntRatio > 0 ? 45 : 0);
        const sat = solidRatio > 0 ? 50 : (learntRatio > 0 ? 60 : 10);
        const light = solidRatio > 0 ? (65 - solidRatio * 25) : (learntRatio > 0 ? 70 : 85);
        return '<div style="aspect-ratio:1.4/1;background:hsl(' + hue + ',' + sat + '%,' + light + '%);border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:11px;color:#333;cursor:default" title="' + L + ': 已学 ' + v.learnt + '/' + v.total + '，稳固 ' + v.solid + '">' + L + '</div>';
      }).join("") + '</div>';
  }

  // 3) Top 10 难词
  const topEl = $("topHardestBox");
  if (topEl) {
    const top = topHardest(10);
    if (!top.length) {
      topEl.innerHTML = '<p style="color:var(--muted)">暂无难词数据（先复习出错几次）</p>';
    } else {
      topEl.innerHTML = top.map((o, i) => {
        return '<div class="top-row" data-jump-id="' + esc(o.word.id) + '" style="padding:6px 8px;border:1px solid var(--line);border-radius:4px;margin-bottom:4px;display:flex;justify-content:space-between;align-items:center;cursor:pointer">' +
          '<div><b style="font-size:12px">' + (i + 1) + '.</b> ' + esc(o.word.hw) + ' <span style="color:var(--muted);font-size:11px">' + esc(o.word.gloss || "") + '</span></div>' +
          '<span style="background:var(--hard-soft);color:var(--hard);padding:2px 8px;border-radius:10px;font-size:11px">错 ' + o.hardCount + ' 次</span>' +
          '</div>';
      }).join("");
      topEl.querySelectorAll("[data-jump-id]").forEach(el => {
        el.onclick = () => {
          const id = el.getAttribute("data-jump-id");
          // 跳到复习视图，并定位到这张卡
          const idx = revQueue.indexOf(id);
          if (idx >= 0) { revIdx = idx; flipped = false; renderReview(); }
          showView("review");
        };
      });
    }
  }

  // 4) 遗忘曲线预测（取最近一张到期卡）
  const fcEl = $("forgetCurveBox");
  if (fcEl) {
    const eod = endToday();
    const dueCards = Object.values(S.cards)
      .filter(c => c.reps > 0 && c.s > 0 && c.due <= eod)
      .sort((a, b) => a.due - b.due);
    if (!dueCards.length) {
      fcEl.innerHTML = '<p style="color:var(--muted)">暂无到期卡可预测</p>';
    } else {
      const card = dueCards[0];
      const curve = predictCurve(card, 30);
      const W = 600, H = 140, L = 30, R = 10, T = 10, B = 25;
      const iw = W - L - R, ih = H - T - B;
      const xStep = iw / 30;
      let g = "";
      // 网格线 + Y 轴标签
      for (let i = 0; i <= 4; i++) {
        const y = T + (ih * i) / 4;
        const val = (1 - i / 4).toFixed(2);
        g += "<line x1='" + L + "' y1='" + y + "' x2='" + (W - R) + "' y2='" + y + "' stroke='var(--line)' stroke-width='1'/>" +
          "<text x='" + (L - 4) + "' y='" + (y + 3) + "' text-anchor='end' font-size='9' fill='var(--muted)'>" + val + "</text>";
      }
      // X 轴标签
      for (let d = 0; d <= 30; d += 5) {
        const x = L + d * xStep;
        g += "<text x='" + x + "' y='" + (H - 6) + "' text-anchor='middle' font-size='9' fill='var(--muted)'>D" + d + "</text>";
      }
      // 曲线
      let path = "";
      curve.forEach((p, i) => {
        const x = L + p.day * xStep;
        const y = T + ih * (1 - p.R);
        path += (i === 0 ? "M" : "L") + x + "," + y;
      });
      g += "<path d='" + path + "' fill='none' stroke='var(--accent)' stroke-width='2'/>";
      // 目标 retention 横线
      const retY = T + ih * (1 - (S.settings.retention || 0.9));
      g += "<line x1='" + L + "' y1='" + retY + "' x2='" + (W - R) + "' y2='" + retY + "' stroke='var(--hard)' stroke-width='1' stroke-dasharray='3,3'/>";
      g += "<text x='" + (W - R) + "' y='" + (retY - 3) + "' text-anchor='end' font-size='9' fill='var(--hard)'>目标 " + (S.settings.retention || 0.9) + "</text>";
      fcEl.innerHTML = "<svg viewBox='0 0 " + W + " " + H + "' style='width:100%;height:auto'>" + g + "</svg>";
    }
  }
}

/* 首装挂起（S.words 为空）期间的统一占位：卡片区 / 词表区 / 顶栏徽标都显示一行
 * 「正在加载 A1 词库…」，不得把空表渲染成「没有词 / 今日已完成」的误导态。
 * 集中在一处，供 renderWords / renderReview / renderHeaderBadge 的首装挂起分支调用。 */
function renderA1BootLoading() {
  $("wCount").textContent = "正在加载 A1 词库…";
  $("wBody").innerHTML = "<tr><td colspan='6' style='text-align:center;color:var(--muted);padding:24px'>正在加载 A1 词库…</td></tr>";
  $("revBoard").style.display = "none";
  $("revEmpty").style.display = "";
  $("revEmptyText").textContent = "正在加载 A1 词库…";
  const bd = $("dueBadge");
  bd.textContent = "正在加载 A1 词库…";
  bd.classList.remove("hot");
}

function renderWords() {
  /* 首装挂起（S.words 为空）：显示加载占位，不得渲染成「没有匹配的单词」的误导态。 */
  if (A1_BOOT_PENDING) { renderA1BootLoading(); return; }
  /* 字母与标签下拉（保留当前选择） */
  const selL = $("wLetter"), selT = $("wTag");
  const curL = selL.value, curT = selT.value;
  const letters = [...new Set(S.words.map(w => (w.letter || (w.hw[0] || "?").toUpperCase()).charAt(0).toUpperCase()))].sort();
  selL.innerHTML = "<option value=''>全部字母</option>" + letters.map(l => "<option>" + esc(l) + "</option>").join("");
  const tags = [...new Set(S.words.flatMap(w => w.tags || []))].sort((a, b) => a.localeCompare(b, "zh"));
  selT.innerHTML = "<option value=''>全部标签</option>" + tags.map(t => "<option>" + esc(t) + "</option>").join("");
  selL.value = curL; selT.value = curT;

  const q = wordFilters.q.toLowerCase();
  const rows = S.words.filter(w => {
    if (q && !(w.hw.toLowerCase().includes(q) || (w.gloss || "").toLowerCase().includes(q))) return false;
    if (wordFilters.letter && (w.letter || "").charAt(0).toUpperCase() !== wordFilters.letter) return false;
    if (wordFilters.tag && !(w.tags || []).includes(wordFilters.tag)) return false;
    /* `!q`：搜索框非空时旁路 scope，搜索 = 全库查询，浏览才受模式限制
     * （docs/plans/workbench-scope-control-and-live-settings.md · Task 3）。
     * 否则核心模式下查非核心词只能去顶栏切到全部，而切模式会立刻把非核心新词补进队列
     * 尾部，中途评一张就落卡、计入 today.nw、吃掉核心配额：查个单词却动了复习进度。
     * 旁路进来的非核心行由下面行模板挂 .out-of-scope 标出，不是静默混进来。 */
    if (wordFilters.scope === "core" && !q && !(w.tags || []).includes("core")) return false;
    const c = S.cards[w.id];
    if (wordFilters.diff === "none" && c && c.reps > 0) return false;
    if (wordFilters.diff === "easy" && !(c && c.reps > 0 && c.d < 4)) return false;
    if (wordFilters.diff === "mid" && !(c && c.reps > 0 && c.d >= 4 && c.d <= 7)) return false;
    if (wordFilters.diff === "hard" && !(c && c.reps > 0 && c.d > 7)) return false;
    const st = wordState(w);
    if (wordFilters.state === "solid" && st.cls !== "solid") return false;
    if (wordFilters.state === "learn" && st.cls !== "learn" && st.cls !== "due") return false;
    if (wordFilters.state === "new" && st.cls !== "new") return false;
    if (wordFilters.state === "due" && !(st.cls === "due" || (c && c.reps > 0 && c.due <= endToday() && st.cls !== "new"))) return false;
    return true;
  });
  $("wCount").textContent = "共 " + rows.length + " / " + S.words.length + " 个单词";
  $("wBody").innerHTML = rows.map(w => {
    const st = wordState(w);
    /* 搜索旁路 scope 进来的非核心词
     * （docs/plans/workbench-scope-control-and-live-settings.md · Task 3）：
     * 判定复用唯一 truth source inScopeWord(w)，别在这里重抄一份 core tag 判定。
     * 搜索为空时谓词已把它们滤掉，这里天然不会命中，故不必再判 q。
     * **极性别反**：class 挂在 inScopeWord(w) 为**假**的那一侧。反过来会把核心词标成
     * 「非本模式」、非核心词标成正常 —— 用户读到的是反话，比不加标签更糟。 */
    return "<tr" + (inScopeWord(w) ? "" : " class='out-of-scope'") + "><td><span class='hw'>" + esc(w.hw) + "</span>" +
      (w.ipa ? "<br><span class='ipa'>" + esc(w.ipa) + "</span>" : "") + "</td>" +
      "<td>" + esc(w.pos || "—") + "</td>" +
      "<td class='gloss-cell'>" + esc(w.gloss || "—") + "</td>" +
      "<td>" + (w.tags || []).map(t => "<span class='tag-chip'>" + esc(t) + "</span>").join("") + "</td>" +
      "<td><button class='st-chip " + st.cls + "' data-act='state' data-id='" + w.id +
        "' title='点击切换：未学习 → 已学习 → 已稳固'>" + st.text + "</button> " +
        "<button class='audio-btn words-audio-sm' data-act='audio' data-id='" + w.id + "' title='播放发音'>🔊</button></td>" +
      "<td class='row-ops'><button data-act='edit' data-id='" + w.id + "'>编辑</button>" +
      "<button data-act='reset' data-id='" + w.id + "'>重置</button>" +
      "<button data-act='del' data-id='" + w.id + "'>删除</button></td></tr>";
  }).join("") || "<tr><td colspan='6' style='text-align:center;color:var(--muted);padding:24px'>没有匹配的单词</td></tr>";
}

function renderSettings() {
  $("setRetention").value = S.settings.retention;
  $("setRetentionVal").textContent = S.settings.retention.toFixed(2);
  $("setDailyNew").value = S.settings.dailyNew;
  $("setNewOrder").value = S.settings.newOrder || "shuffle";
  $("setPlanDate").value = S.settings.planDate || "";
  renderPlan();
  // ---- TTS ----
  $("setTtsEngine").value = (S.settings.tts && S.settings.tts.engine) || "auto";
  $("setTtsAuto").checked = !!(S.settings.tts && S.settings.tts.autoPlay);
  $("setTtsRate").value = (S.settings.tts && S.settings.tts.rate) || 0.9;
  $("setTtsRateVal").textContent = (+$("setTtsRate").value).toFixed(2) + "×";
  const kb = storageUsage() / 1024, limitKb = 5 * 1024;  // 5120 KB = 5 MB
  const used = kb >= 1024 ? (kb / 1024).toFixed(2) + " MB" : Math.round(kb) + " KB";
  $("storageInfo").textContent = "当前占用 " + used + " / 约 5120 KB（" +
    (kb / limitKb * 100).toFixed(1) + "%，localStorage 上限约 5 MB）";
  // ---- 内嵌音频词典 ----
  const nEmb = (typeof EMBEDDED_AUDIO === 'object' && EMBEDDED_AUDIO) ? Object.keys(EMBEDDED_AUDIO).length : 0;
  const embSizeKB = nEmb ? Math.round(nEmb * 8 * 0.75 / 1024) : 0;  // 粗估 base64 体积
  $("embeddedAudioInfo").textContent = nEmb
    ? "内嵌离线音频: " + nEmb + " 个词（约 " + embSizeKB + " KB，离线可播放，无需网络）"
    : "内嵌离线音频: 0（需网络或浏览器语音）";
  // F2 · 渲染历史版本面板
  renderSnapshots();
}

async function renderSnapshots() {
  if (typeof indexedDB === "undefined") {
    $("snapshotsPanel").style.display = "none";
    return;
  }
  $("snapshotsPanel").style.display = "block";
  const snaps = await idbListSnapshots();
  const c = $("snapshotsList");
  if (!snaps.length) {
    c.innerHTML = '<p style="color:var(--muted)">暂无快照（启动后会自动创建今日快照）</p>';
    return;
  }
  const rows = snaps.map(s => {
    const d = new Date(s.ts);
    const dateStr = d.toLocaleDateString() + " " + d.toLocaleTimeString();
    const cardCount = Object.keys(s.cards || {}).length;
    const wordCount = (s.words || []).length;
    return '<div style="padding:6px 8px;border:1px solid var(--line);border-radius:4px;margin-bottom:4px;display:flex;justify-content:space-between;align-items:center">' +
      '<div><div style="font-weight:600">' + dateStr + '</div>' +
      '<div style="color:var(--muted);font-size:11px">' + wordCount + ' 词 · ' + cardCount + ' 张卡片</div></div>' +
      '<div style="display:flex;gap:4px">' +
      '<button class="btn sm ghost" data-restore="' + s.ts + '">恢复</button>' +
      '<button class="btn sm danger" data-delete="' + s.ts + '">删除</button>' +
      '</div></div>';
  }).join("");
  c.innerHTML = rows;
  // 绑定按钮（事件委托）
  c.querySelectorAll("button[data-restore]").forEach(btn => {
    btn.onclick = async () => {
      const ts = +btn.getAttribute("data-restore");
      if (!await confirmDlg("恢复此快照？当前进度会被覆盖（含历史快照中可能没有的新进度）")) return;
      const r = await idbRestoreSnapshot(ts);
      if (r) { toast("恢复成功，刷新中…"); setTimeout(() => location.reload(), 800); }
      else toast("恢复失败");
    };
  });
  c.querySelectorAll("button[data-delete]").forEach(btn => {
    btn.onclick = async () => {
      const ts = +btn.getAttribute("data-delete");
      if (!await confirmDlg("删除此快照？")) return;
      const r = await idbDeleteSnapshot(ts);
      if (r) { toast("已删除"); renderSnapshots(); }
      else toast("删除失败");
    };
  });
}

function renderPlan() {
  const p = planCalc();
  if (!p) {
    $("planInfo").textContent = "尚未设定目标日期";
    $("planDetail").textContent = "设定日期后显示每日建议学习量";
    $("btnApplyPlan").disabled = true;
    return;
  }
  $("planInfo").textContent = "剩余 " + p.remaining + " 词 · " + p.days + " 天";
  $("planDetail").textContent = "建议每日新词 " + p.daily + " 个（当前上限 " + S.settings.dailyNew + "）";
  $("btnApplyPlan").disabled = p.remaining === 0;
}

function renderHeaderBadge() {
  /* 首装挂起（S.words 为空）：徽标显示加载态，不得渲染成「今日已完成 ✓」的误导态。 */
  if (A1_BOOT_PENDING) { renderA1BootLoading(); return; }
  const eod = endToday();
  /* 徽标口径必须与 buildReviewQueue 一致（同一个 wordFilters.scope）：
   * 否则核心模式下顶栏会挂着一堆永远进不了队列的非核心待学数，永远清不到「已完成」 */
  let due = 0, nw = 0;
  for (const id in S.cards) {
    const c = S.cards[id], w = wordById(id);
    if (c.reps > 0 && !c.manual && c.due <= eod && w && inScopeWord(w)) due++;
  }
  const t = S.log[todayStr()];
  nw = Math.max(0, S.settings.dailyNew - ((t && t.nw) || 0));
  const pending = due + Math.min(nw, S.words.filter(w => !S.cards[w.id] && inScopeWord(w)).length);
  const b = $("dueBadge");
  /* 模式与待学数一体呈现：队列变短时用户要能分辨是「学完了」还是「切了范围」。
   * 待学 / 已完成两个分支都带前缀 —— 只给待学分支加的话，核心模式刷完后模式状态凭空消失。 */
  const scopeLabel = wordFilters.scope === "core" ? "⭐核心" : (wordFilters.scope === "reader" ? "生词" : (wordFilters.scope === "a2" ? "📘A2" : (wordFilters.scope === "b1" ? "📗B1" : "全部")));
  b.textContent = pending > 0
    ? scopeLabel + " · 今日待学 " + pending
    : scopeLabel + " · 今日已完成 ✓";
  b.classList.toggle("hot", pending > 0);
}
