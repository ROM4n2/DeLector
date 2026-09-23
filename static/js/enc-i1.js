/* DeLector - 遇见区 i+1 就近选材纯函数（Phase B，纯逻辑 ES module）
 *
 * 目标：把「按本机背词 deck 算覆盖率 → 分区间 → 排序 → 取推荐」实现为零依赖纯函数，
 * 供遇见区列表在**不点开任何一篇**的前提下标出「哪篇正好读（i+1）」并置顶。
 *
 * 纪律（与 deck-bridge.js 同族）：
 *   - **零 import**：浏览器（ESM）与 Node（去 ESM 关键字后注入 node:vm 沙箱）都能
 *     直跑，无需构建、无需 package.json 的 "type":"module"。
 *   - **模块顶层不碰浏览器全局**：localStorage / document / window 一律不出现；
 *     `knownSet` 由调用方注入（encounter.js 组装 buildKnownSet(loadDeck(...))），
 *     本模块**不得** import deck-bridge.js。
 *   - **坏输入降级不抛**：非对象 entry / 非正 total_tokens / 非数组 lemma_seq → 一律
 *     返回 available=false 的降级结果，绝不抛异常。
 *   - **绝不改入参**：rankEntries 返回新数组，不 sort / 不改原数组及其元素对象。
 *
 * 覆盖率口径（MUST 与阅读视图 annotate 的 known_rate 逐位一致）：
 *   knownTokens = entry.lemma_seq 中命中 knownSet（元素为**已小写**的剥冠词词头）的
 *   token 数；rate = knownTokens / entry.total_tokens。
 *   分母 MUST 用服务端 `total_tokens`，MUST NOT 用 lemma_seq.length（两者实测同值，但
 *   分母的权威来源是 total_tokens —— 混用会在二者不一致时静默漂移）。
 *
 * entry 形状 = GET /api/encounter/texts/index 的 items 元素：{id, title, level, word_count, total_tokens, lemma_seq}（total_tokens 为 null 时视为 available=false）
 */
"use strict";

/**
 * 区间阈值**单点定义**（半开区间；渲染层不得散落 0.85 / 0.97 字面量，一律读此常量）：
 *   i1   = [i1[0], i1[1])   = [0.85, 0.97)  —— 正好读（i+1）
 *   easy = [easy[0], +∞)    = [0.97, +∞)    —— 偏简单
 *   hard = (-∞, hard[1])    = (-∞, 0.85)    —— 偏难
 * 注：用 `Infinity` 表达开区间端点（JSON 序列化为 null，故探针直接读常量而非往返 JSON）。
 */
export const I1_BANDS = { i1: [0.85, 0.97], easy: [0.97, Infinity], hard: [-Infinity, 0.85] };

/** band 分组排序优先级：i1 最前、easy 次之、hard 最后（available=false 另列最末）。 */
const BAND_ORDER = { i1: 0, easy: 1, hard: 2 };

/** 参数是否为可用的 knownSet（Set 或任何具备 has() 的集合）。 */
function _setLike(x) {
  return !!x && typeof x.has === "function";
}

/** available=false 的统一降级结果（rate 不参与排序）。 */
function _unavailable() {
  return { available: false, knownTokens: 0, totalTokens: 0, rate: 0, band: null };
}

/**
 * bandOf(rate) -> "i1" | "easy" | "hard"
 *
 * 半开区间判定：rate < 0.85 → "hard"；0.85 ≤ rate < 0.97 → "i1"；rate ≥ 0.97 → "easy"。
 * 阈值一律读 I1_BANDS（本函数内不得出现裸露的 0.85 / 0.97）。
 * 边界逐条钉死：0.84→hard / 0.85→i1 / 0.96→i1 / 0.97→easy。
 * 非有限数值（NaN / ±Infinity / 非 number）一律归 "hard" —— 覆盖率不可信时绝不误报 i1。
 */
export function bandOf(rate) {
  const r = Number(rate);
  if (!Number.isFinite(r)) return "hard";
  if (r < I1_BANDS.hard[1]) return "hard";
  if (r < I1_BANDS.easy[0]) return "i1";
  return "easy";
}

/**
 * coverageOf(knownSet, entry) -> {available, knownTokens, totalTokens, rate, band}
 *
 * knownSet：已小写的剥冠词词头集合（由调用方注入，可为任意含 has() 的集合）。
 * entry：索引端点返回的一项（含 `lemma_seq: string[]` 与 `total_tokens: number`）。
 *
 * 覆盖率算法（逐字固定）：
 *   knownTokens = entry.lemma_seq.filter((l) => knownSet.has(String(l).toLowerCase())).length;
 *   rate = knownTokens / entry.total_tokens;   // 分母用 total_tokens，非 lemma_seq.length
 *
 * 降级（available=false，返回 _unavailable()）：entry 非对象 / total_tokens 非正数 /
 * lemma_seq 非数组；另对非集合型 knownSet 亦降级（坏输入不抛）。
 */
export function coverageOf(knownSet, entry) {
  if (!_setLike(knownSet) || !entry || typeof entry !== "object") return _unavailable();
  const total = entry.total_tokens;
  if (!(typeof total === "number" && total > 0)) return _unavailable();
  if (!Array.isArray(entry.lemma_seq)) return _unavailable();
  const knownTokens = entry.lemma_seq.filter((l) => knownSet.has(String(l).toLowerCase())).length;
  const rate = knownTokens / entry.total_tokens;
  return {
    available: true,
    knownTokens: knownTokens,
    totalTokens: total,
    rate: rate,
    band: bandOf(rate),
  };
}

/** 比较两个 id（数字按数值、其余按字符串）用于同分排序，保证确定性。 */
function _cmpId(x, y) {
  if (typeof x === "number" && typeof y === "number") return x - y;
  const sx = String(x == null ? "" : x);
  const sy = String(y == null ? "" : y);
  return sx < sy ? -1 : sx > sy ? 1 : 0;
}

/**
 * 排序比较器（入参为 rankEntries 的装饰对象 {available, band, rate, id, _index}）：
 *   1) available=true 在前；
 *   2) band 优先级 i1 > easy > hard；
 *   3) 组内 rate 降序；
 *   4) 同分按 id 升序；
 *   5) 末位 _index 升序（保 available=false 组「入参相对顺序」且排序确定）。
 */
function _compareRanked(a, b) {
  if (a.available !== b.available) return a.available ? -1 : 1;
  if (a.available) {
    const byBand = BAND_ORDER[a.band] - BAND_ORDER[b.band];
    if (byBand !== 0) return byBand;
    if (a.rate !== b.rate) return b.rate - a.rate;
    const byId = _cmpId(a.id, b.id);
    if (byId !== 0) return byId;
  }
  return a._index - b._index;
}

/**
 * rankEntries(knownSet, entries) -> Array（**新数组，绝不改入参**）
 *
 * 对每个 entry 调 coverageOf，按 _compareRanked 排序后返回**全新对象**组成的新数组：
 * `{ id, available, knownTokens, totalTokens, rate, band, entry }`（`entry` 为原对象引用，
 * 供调用方取 title/level 等元信息；本函数不改其任何字段）。
 * 非数组 entries 视为空数组；band 优先级 i1 > easy > hard，available=false 一律排最后。
 */
export function rankEntries(knownSet, entries) {
  const src = Array.isArray(entries) ? entries : [];
  const decorated = src.map(function (entry, index) {
    const cov = coverageOf(knownSet, entry);
    return {
      id: entry && typeof entry === "object" ? entry.id : undefined,
      available: cov.available,
      knownTokens: cov.knownTokens,
      totalTokens: cov.totalTokens,
      rate: cov.rate,
      band: cov.band,
      entry: entry,
      _index: index,
    };
  });
  decorated.sort(_compareRanked);
  return decorated.map(function (d) {
    return {
      id: d.id,
      available: d.available,
      knownTokens: d.knownTokens,
      totalTokens: d.totalTokens,
      rate: d.rate,
      band: d.band,
      entry: d.entry,
    };
  });
}

/**
 * topPick(ranked) -> object | null
 *
 * 返回排序后数组里**首条** `band === "i1"` 的条目；无 i1（或入参非数组）→ null。
 * 供推荐条取「正好读」的那一篇。
 */
export function topPick(ranked) {
  if (!Array.isArray(ranked)) return null;
  return ranked.find(function (r) {
    return r && r.band === "i1";
  }) || null;
}

/**
 * hasCoverage(knownSet) -> boolean
 *
 * `knownSet.size > 0`；供 UI 决定是否显示推荐条 / 引导文案（空集 → 显示引导，不推 0% 短文）。
 * 非集合型输入安全返回 false。
 */
export function hasCoverage(knownSet) {
  return !!knownSet && typeof knownSet.size === "number" && knownSet.size > 0;
}
