/* DeLector - 「从电脑导入」拉取纯逻辑（遇见区 WiFi 内容分发，纯逻辑 ES module）
 *
 * 本模块承载「从电脑导入」中所有与 DOM 无关的纯逻辑，供 encounter.js 的页面
 * 编排层复用。抽离动机（与 deck-bridge.js 同族）：让 Node 侧能把本文件逐字节
 * 拷成 .mjs 直跑断言「地址归一 / 记忆读写 / 包列表数据映射」——这些是易回归的
 * 关键路径，不该只靠「字符串存在」死断言。
 *
 * Node 可测性硬约束（同 Task A5 deck-bridge 约定）：
 *   - **零 import**：纯逻辑、无任何依赖，浏览器（ESM）与 Node（临时拷成 .mjs
 *     直读）两处都能跑，无需 package.json 的 "type":"module"。
 *   - **模块顶层不碰浏览器全局**：localStorage/window/document/fetch 一律不出现；
 *     storage 由调用方注入（浏览器传 window.localStorage，Node 测桩传 getItem 对象）。
 *   - 坏输入（坏 JSON / 缺字段 / 空串）一律安全降级，不抛异常。
 *
 * 架构安全边界（ADR + Plan 全局约束，红线精神）：
 *   - 前端**只**调本机相对路径 /api/encounter/pull-pack（同源零跨域）；
 *     出站拉取由手机服务端完成（Android 实例绑回环，出站不受监听限制）。
 *   - desktop_base 仅作为 POST body 的一个字段交给本机服务端，**绝不**在前端
 *     拼进 fetch()/api() 直连桌面（跨域且违背架构）。本模块只做「归一 + 记忆读写」，
 *     不发起任何请求。
 *
 * 暴露的纯函数（全部可被 Node 测）：
 *   DESKTOP_KEY                          -> "enc.desktop.v1"（localStorage 记忆键）
 *   normalizeDesktopBase(raw)            -> string（去掉尾斜杠）；非法抛 Error
 *   readDesktopBase(storage)             -> string（无记忆/坏值 → ""）
 *   writeDesktopBase(storage, value)     -> bool（写成功 true；storage 不可用 false）
 *   mapPackRows(packs)                   -> [{pack_id, title, level, word_count}]
 *   pullPackRequest(desktopBase, packId) -> {desktop_base, pack_id?}（POST body）
 */
"use strict";

// 桌面地址的记忆键（固定名，Plan Task 3 契约）。
export const DESKTOP_KEY = "enc.desktop.v1";

// 本机拉取代理端点（同源；前端唯一允许的出站入口是手机服务端）。
export const PULL_ENDPOINT = "/api/encounter/pull-pack";

/**
 * 归一桌面地址：去首尾空白、去尾斜杠。必须 http(s):// 前缀且带回环/主机，
 * 否则抛 Error（带中文人话）。与后端 `_normalize_desktop_base` 同口径（前端
 * 先行校验只为即时反馈；真正的安全闸在服务端的 _require_localhost + 校验）。
 */
export function normalizeDesktopBase(raw) {
  const base = String(raw == null ? "" : raw).trim().replace(/\/+$/, "");
  if (!/^https?:\/\//.test(base) || base === "http:/" || base === "https:/") {
    throw new Error("地址需以 http:// 或 https:// 开头，例如 http://192.168.1.5:8000");
  }
  // 去掉 scheme 后必须还剩主机名（挡掉 "http://" 之类只有 scheme 的输入）。
  const rest = base.replace(/^https?:\/\//, "");
  if (!rest) {
    throw new Error("地址需以 http:// 或 https:// 开头，例如 http://192.168.1.5:8000");
  }
  return base;
}

/** 读记忆里的桌面地址（无记忆 / 坏 storage → 空串，不抛）。 */
export function readDesktopBase(storage) {
  try {
    const raw = storage && storage.getItem ? storage.getItem(DESKTOP_KEY) : null;
    return typeof raw === "string" ? raw : "";
  } catch (e) {
    return "";
  }
}

/** 写记忆里的桌面地址（写成功 true；storage 不可用/配额满 → false，不抛）。 */
export function writeDesktopBase(storage, value) {
  try {
    if (!storage || !storage.setItem) return false;
    storage.setItem(DESKTOP_KEY, String(value == null ? "" : value));
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * 把本机服务端代理回来的货架清单映射成渲染行（字段白名单 + 类型归一）。
 * 只保前端要用的 4 个字段（pack_id/title/level/word_count），忽略其余（含
 * 任何潜在机密字段），word_count 非数字归 0，字符串字段一律 String()。
 */
export function mapPackRows(packs) {
  const arr = Array.isArray(packs) ? packs : [];
  return arr.map((p) => {
    const o = p && typeof p === "object" ? p : {};
    return {
      pack_id: o.pack_id == null ? "" : String(o.pack_id),
      title: o.title == null ? "" : String(o.title),
      level: o.level == null ? "" : String(o.level),
      word_count: typeof o.word_count === "number" ? o.word_count : 0,
    };
  });
}

/**
 * 构造 POST /api/encounter/pull-pack 的请求体。
 * packId 为空 → 只带 desktop_base（代理货架清单）；非空 → 追加 pack_id（拉取落库）。
 */
export function pullPackRequest(desktopBase, packId) {
  const body = { desktop_base: String(desktopBase == null ? "" : desktopBase) };
  if (packId) body.pack_id = String(packId);
  return body;
}
