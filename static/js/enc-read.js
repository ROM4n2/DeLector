/* DeLector - 遇见区「已读状态」纯函数（零依赖 ES module）
 *
 * 目标：把「遇见区哪些文章已读过」的持久化读写实现为零依赖纯函数，供遇见区列表在
 * 不点开任何一篇的前提下标出「哪篇还没读」并可以「取首个未读」置顶。
 *
 * 纪律（与 enc-i1.js / deck-bridge.js 同族）：
 *   - **零 import**：浏览器（ESM）与 Node（去 ESM 关键字后注入 node:vm 沙箱）都能
 *     直跑，无需构建、无需 package.json 的 "type":"module"。
 *   - **模块顶层不碰浏览器全局**：localStorage / document / window 一律不出现；
 *     storage 由调用方注入（浏览器传 window.localStorage，测试/探针传桩对象）。
 *   - **坏输入降级不抛**：坏 JSON / 缺键 / 非对象 / storage 不可用 / setItem 抛异常
 *     → 一律降级（读返回空态、写返回 false），绝不抛异常。
 *   - **绝不改入参**：pickUnread 只读 ranked，不 sort / 不改原数组及其元素。
 *
 * 存储 schema（单点定义于 READ_KEY，MUST NOT 改成 `enc.` 前缀 —— `delector_` 前缀
 * 是随备份导出/还原的契约）：
 *   localStorage[READ_KEY] = JSON.stringify({ v: 1, read: { [id: string]: tsMs } })
 *   tsMs 为写入时注入的毫秒时间戳（可能是 0，故幂等判据 MUST 用 hasOwnProperty，
 *   MUST NOT 用真值判断）。
 */

"use strict";

/** 本地持久键（**单点定义**；`delector_` 前缀 = 随备份导出/还原的契约，勿改）。 */
export const READ_KEY = "delector_encounter_read_v1";

/** 读态 schema 版本号（写入时随盘持久化，便于日后迁移）。 */
const SCHEMA_V = 1;

/**
 * 空读态（loadRead 的无键 / 坏 JSON / 非对象、以及所有坏输入的统一降级结果）。
 * 每次返回**新对象**，避免调用方共享同一引用而被就地修改。
 */
function _emptyState() {
  return { v: SCHEMA_V, read: {} };
}

/**
 * 参数是否为可用 storage（形状 {getItem(k), setItem(k,v), removeItem(k)}）。
 * null / undefined / 非对象 / 缺任一方法 → false（降级为 no-op，不抛）。
 */
function _storageLike(s) {
  return (
    !!s &&
    typeof s === "object" &&
    typeof s.getItem === "function" &&
    typeof s.setItem === "function" &&
    typeof s.removeItem === "function"
  );
}

/** read 值是否为合法映射对象（非 null / 非数组）。 */
function _readMap(x) {
  return !!x && typeof x === "object" && !Array.isArray(x);
}

/**
 * _persist(storage, read) -> boolean
 *
 * 把 `{v, read}` 序列化写入 storage[READ_KEY]。副作用：写盘一次。
 * setItem 抛异常（配额 / 私隐模式）→ 返回 false 且**不抛**（调用方据此降级）。
 */
function _persist(storage, read) {
  try {
    storage.setItem(READ_KEY, JSON.stringify({ v: SCHEMA_V, read: read }));
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * loadRead(storage) -> {v:number, read:{[id:string]: tsMs}}
 *
 * 读取并解析已读态。副作用：读盘一次。
 * 版本号 `v`：解析成功且盘上 `v` 为**有限数字**时**透传该值**（便于日后 v:2 迁移
 * 检测，MUST NOT 硬编码回 SCHEMA_V）；否则回落 SCHEMA_V。
 * 降级（一律返回**空态** {v:1, read:{}}，绝不抛）：storage 不可用 / 无键（null）/
 * 坏 JSON / 顶层非对象或为数组 / 缺 read 键 / read 非对象。
 * 返回的 read 为本次解析出的**新对象**（不与 storage 共享引用）。
 */
export function loadRead(storage) {
  if (!_storageLike(storage)) return _emptyState();

  let raw = null;
  try {
    raw = storage.getItem(READ_KEY);
  } catch (e) {
    return _emptyState();
  }
  if (raw == null) return _emptyState();

  let parsed = null;
  try {
    parsed = JSON.parse(raw);
  } catch (e) {
    return _emptyState();
  }
  if (!_readMap(parsed) || !_readMap(parsed.read)) return _emptyState();
  const v = typeof parsed.v === "number" && Number.isFinite(parsed.v) ? parsed.v : SCHEMA_V;
  return { v: v, read: parsed.read };
}

/**
 * markRead(storage, id, nowMs) -> boolean
 *
 * 把 id 标记为已读，时间戳记为 nowMs。副作用：仅在**首次**标记时写盘一次。
 * 幂等：已读（read 含 String(id) 键）→ 返回 false 且**不写盘**。
 *   判据 MUST 用 `Object.prototype.hasOwnProperty.call(read, String(id))`，
 *   MUST NOT 用真值判断（时间戳可能为 0，真值判断会误判未读而重复写盘）。
 * 降级（返回 false 且不抛）：storage 不可用 / 写盘失败（setItem 抛异常）。
 */
export function markRead(storage, id, nowMs) {
  if (!_storageLike(storage)) return false;

  const key = String(id);
  const state = loadRead(storage);
  if (Object.prototype.hasOwnProperty.call(state.read, key)) return false;

  state.read[key] = typeof nowMs === "number" && Number.isFinite(nowMs) ? nowMs : 0;
  return _persist(storage, state.read);
}

/**
 * isRead(state, id) -> boolean
 *
 * read 态中是否含 String(id) 键。纯读，无副作用。
 * 未命中 / id 为 null / state 非对象 / state.read 非对象 → false（不抛）。
 * 判据同样用 hasOwnProperty（时间戳为 0 仍算已读）。
 */
export function isRead(state, id) {
  if (!state || typeof state !== "object") return false;
  if (!_readMap(state.read)) return false;
  if (id == null) return false;
  return Object.prototype.hasOwnProperty.call(state.read, String(id));
}

/**
 * unmarkRead(storage, id) -> boolean
 *
 * 删除 id 的已读标记。副作用：仅在**确实删除**时写盘一次。
 * 幂等：键不存在 → 返回 false 且**不写盘**。
 * 降级（返回 false 且不抛）：storage 不可用 / 写盘失败。
 */
export function unmarkRead(storage, id) {
  if (!_storageLike(storage)) return false;

  const key = String(id);
  const state = loadRead(storage);
  if (!Object.prototype.hasOwnProperty.call(state.read, key)) return false;

  delete state.read[key];
  return _persist(storage, state.read);
}

/**
 * pickUnread(ranked, readState) -> object | null
 *
 * 返回 ranked 中**首个未读**条目（用 isRead(readState, entry.id) 判读）；全部已读
 * 或入参非数组 / 空数组 → null。纯函数，**绝不改入参**（不 sort / 不改原数组及其元素）。
 */
export function pickUnread(ranked, readState) {
  if (!Array.isArray(ranked)) return null;
  for (let i = 0; i < ranked.length; i++) {
    const entry = ranked[i];
    const id = entry && typeof entry === "object" ? entry.id : undefined;
    if (!isRead(readState, id)) return entry;
  }
  return null;
}
