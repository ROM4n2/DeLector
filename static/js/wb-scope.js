/**
 * wb-scope.js —— 词表 scope / CEFR 等级判定（C7 Task 5 · 块 5：wbscope）
 *
 * 本文件内容从 static/german/workbench.html 的内联脚本**逐字节**搬出，未改写一个字符
 * （两段片段的 sha256 与原文逐段相等，见本次提交说明）：
 *   1) 等级判定数据驱动族：CEFR_BY_PREFIX 前缀表 + cefrFromId() + cefrOf()、
 *      OTHER_LEVEL_SCOPES、SCOPE_PREDICATES 谓词表、isInScope() 唯一判定入口、
 *      inScopeWord() 薄封装 —— 连同上方「Task 5 · 等级判定数据驱动（ADR-0011）」
 *      分节 banner 与各段说明注释（含「多级核心词档扩展位」预留注释）；
 *   2) 词表过滤态 wordFilters（含其上方 scope 字段说明）+ wordState() + wordStateKey()
 *      —— renderWords 的过滤链直接读这三个声明，故与判定链同住一个模块。
 * 搬动前后唯一新增的字节是本段说明性文件头（两段之间只加了分隔说明与空行）。
 *
 * 范围判据（为什么是这九个，而不是「所有名字里带 Scope 的声明」）：
 *   · 收进来的都是**同一条判定链**上的声明：id 前缀 → 等级（CEFR_BY_PREFIX /
 *     cefrFromId / cefrOf）、scope 名 → 谓词（OTHER_LEVEL_SCOPES / SCOPE_PREDICATES）、
 *     唯一判定入口（isInScope）与其单参薄封装（inScopeWord）、被谓词读的过滤态
 *     （wordFilters）与被同一过滤链读的状态分档（wordState / wordStateKey）；
 *   · 刻意**没收** refilterReviewQueueForScope() —— 它是会话队列手术（revQueue / revIdx /
 *     renderReview 三件套），与会话内存态强耦合，归 review-queue 块；
 *   · 也**没收** syncScopeControls() —— 它是顶栏 #scopeSeg 的 DOM 同步（控件的 .active
 *     态），归顶栏/设置 UI；两者留在 workbench.html，只**调用**本模块的判定入口；
 *   · 也没收 setWordState()（写卡 + FSRS 调度联动，是 wordState 的**下游写方**）与
 *     normalizeWord()（词条归一化，只借用 cefrFromId 这一条边）。
 *
 * 引入方式：入口页用**普通** <script src> 加载，全序为
 *     wb-seed-data.js → wb-idb.js → wb-tts.js → wb-views.js → wb-sync.js → wb-scope.js
 *     → 主内联脚本
 * 刻意不用 ES Module：Android/WebView 的模块加载语义未真机验证（计划 Fog of War
 * Unknown 2），必须保留整体回退成内联脚本的能力。本文件零 import / export。
 *
 * 为什么排在队尾（紧邻主内联脚本）：本文件是**纯声明**，加载期一行都不执行 ——
 * SCOPE_PREDICATES 的值是箭头函数（只在被调用时求值）、wordFilters 只建一个字面量 ——
 * 所以「排在前面会撞 TDZ」这个风险在本文件不存在；位置由**阅读顺序**决定：紧贴主内联脚本，
 * 读作「判定链在最后交给你」。正向依赖为零，反向依赖全是运行期的：
 *   wb-views.js 的 renderWords / renderHeaderBadge、主内联脚本的 buildReviewQueue /
 *   refilterReviewQueueForScope / renormalizeQueueTail / backfillCoreWords / normalizeWord /
 *   顶栏 #scopeSeg handler 与词表 filter 控件 —— 都在启动或用户操作后才读这里的声明。
 *
 * 跨文件依赖（全部在**运行期**解析；顶层 let/const/function 落在同一全局词法环境）：
 *   cefrFromId / cefrOf   ← normalizeWord、backfillCoreWords（主内联脚本）
 *   isInScope / inScopeWord ← renderWords、renderHeaderBadge（wb-views.js）、
 *                             buildReviewQueue / refilterReviewQueueForScope /
 *                             renormalizeQueueTail（主内联脚本）
 *   wordState / wordStateKey ← renderWords（wb-views.js）、setWordState（主内联脚本）
 *   wordFilters ← 顶栏 #scopeSeg handler、词表 filter 控件、syncScopeControls（主内联脚本）
 * => 这些声明只能在主内联脚本解析完成之后被调用；反过来，主内联脚本与各模块仍可直接
 *    读写本文件的顶层声明（普通脚本共享同一个全局词法环境）。
 *    任何「在加载期调用 isInScope / wordState」的写法都会撞上 TDZ，不要加。
 *
 * 严格模式：搬出前这些代码位于主内联脚本的 "use strict" 之下，本文件不带该指令
 * （与 wb-tts.js / wb-idb.js / wb-views.js / wb-sync.js 一致）。已逐条核对：本片段不依赖
 * 严格/宽松模式的任何差异（无未声明变量赋值、无裸 this、无 arguments.callee、
 * 无重复形参、无八进制字面量）。
 */

/* ======================================================================
 * Task 5 · 等级判定数据驱动（ADR-0011 决策 3 / §5-#4 判定唯一入口）
 *  - cefrOf：全文件唯一的等级推导口径，与 normalizeWord 共用同一张前缀表
 *    （CEFR_BY_PREFIX + cefrFromId），禁止第二套推导；
 *  - SCOPE_PREDICATES：每档一条声明式谓词，新增等级 = 加一行配置；
 *  - isInScope：scope 判定唯一入口；inScopeWord 只是它的单参薄封装
 *    （旧名兼容全部既有调用点）。
 * ==================================================================== */
const CEFR_BY_PREFIX = [["a1-", "A1"], ["a2-", "A2"], ["b1-", "B1"]];

/** id 前缀 → 等级；无已知前缀（reader card-* / core-* 自定义词）返回 null。 */
function cefrFromId(id) {
  for (const [prefix, level] of CEFR_BY_PREFIX) {
    if (String(id || "").startsWith(prefix)) return level;
  }
  return null;
}

/** 词的 CEFR 等级：显式 cefr 字段优先，否则按 id 前缀推导（与 normalizeWord 同口径）。 */
function cefrOf(w) {
  if (!w) return null;
  return w.cefr || cefrFromId(w.id);
}

/* all 档的排除规则由配置生成，不手写 OR 链：
 *  - OTHER_LEVEL_SCOPES：会随 sync 并入 S.words 的其他已开放等级，新增等级在此
 *    追加其 scope 名即可。T6（ADR-0011）开 B1 档 + syncB1CardsFromServer 落库后
 *    b1 正式列入 —— 「A1 全量」不再混入 B1 形态词；
 *  - 精读生词：custom 且带 reader 标记。这是改造前 all 分支的收窄口径，刻意比
 *    reader 谓词窄 —— 仅 card- 前缀命中、不带 custom 的词在 all 档仍然可见。 */
const OTHER_LEVEL_SCOPES = ["a2", "b1"];
/* 标签分工（词条 tags 数组）：
 *  - 等级标签 a1 / a2 / b1：课程等级身份，一条课程词恰属一个等级；词库「全部标签」
 *    下拉据此筛出「某一等级全量」（用户需求：不局限 core 也能单看 A1 / A2 / B1）。
 *  - 语义标签 core：核心词标记，与等级标签共存（A1 核心词 = a1 + core）；
 *  - 语义标签 reader：精读生词来源标记，连同 card- 前缀 id 一起被 reader 档谓词识别。
 * 每档一条声明式谓词（下表即数据驱动入口），新增等级 = 加一行配置。 */
const SCOPE_PREDICATES = {
  core: w => (w.tags || []).includes("core"),
  /* reader 谓词收窄：去掉 w.custom 兜底 —— 否则任何自定义词（含 22 条 A1 核心补缺词
   * core-*）都会被当成精读生词，同时出现在「A1 全量」与「精读生词」两档。
   * 精读生词真实身份信号 = reader 标记 或 card- 前缀 id（syncReaderCardsFromServer 落库形态）。 */
  reader: w => !!((w.tags || []).includes("reader") || String(w.id || "").startsWith("card-")),
  a2: w => cefrOf(w) === "A2" || (w.tags || []).includes("a2"),
  /* b1 谓词：T6（ADR-0011）已开入口 —— 顶栏 #scopeSeg 有 B1 档位按钮 +
   * 切换处 syncB1CardsFromServer 落库，不再是预留谓词 */
  b1: w => cefrOf(w) === "B1" || (w.tags || []).includes("b1"),
  all: w => !OTHER_LEVEL_SCOPES.some(s => SCOPE_PREDICATES[s](w)) && !(w.custom && (w.tags || []).includes("reader")),
};

/* 多级核心词档扩展位（预留 · R8 交付 3）：
 * 后端 delector.core.lexicon.core_ids_by_level() 现仅 A1 有核心词名单，
 * A2/B1/B2 为空集占位。将来开放某级核心词档 = 三步纯数据改动，无需改判定逻辑：
 *   ① 后端 core_ids_by_level() 登记该级 id 集；
 *   ② 顶栏 #scopeSeg 增加一个 data-scope 档位按钮；
 *   ③ 在 SCOPE_PREDICATES 本表增加一行谓词（本表即数据驱动入口）。
 * 本次刻意不新增按钮/谓词，避免死代码与档位数护栏漂移。 */

/** scope 判定唯一入口。未注册的 scope 沿用改造前的兜底语义（恒真）。 */
function isInScope(w, scope) {
  const pred = SCOPE_PREDICATES[scope];
  return pred ? !!pred(w) : true;
}

/* 核心词模式判定 helper：全局唯一 truth source 是 isInScope(w, wordFilters.scope) */
function inScopeWord(w) {
  return !w || isInScope(w, wordFilters.scope);
}

/* ----------------------------------------------------------------------
 * 第二段：词表过滤态 wordFilters + 状态分档 wordState / wordStateKey
 * （在 workbench.html 里这两段隔着一百多行非本族声明，搬来时只保留这段分隔说明）
 * -------------------------------------------------------------------- */

/* scope: "all"=全部词 | "core"=仅核心词（按 core tag 过滤，默认 all） */
const wordFilters = { q: "", letter: "", tag: "", diff: "", state: "", scope: "all" };

function wordState(w) {
  const c = S.cards[w.id];
  if (!c || c.reps === 0) return { cls: "new", text: "未学" };
  if (c.manual === "solid") return { cls: "solid", text: "手动稳固" };
  if (c.s >= 21) return { cls: "solid", text: "稳固 · " + fmtMD(c.due) };
  if (c.due <= endToday()) return { cls: "due", text: "待复习 · " + fmtMD(c.due) };
  return { cls: "learn", text: "S" + (c.s < 10 ? c.s.toFixed(1) : Math.round(c.s)) + "d · " + fmtMD(c.due) };
}

function wordStateKey(w) {
  const c = S.cards[w.id];
  if (!c || c.reps === 0) return "new";
  return c.manual === "solid" ? "solid" : "learn";
}
