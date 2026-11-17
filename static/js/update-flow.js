/* DeLector - 应用内更新面板的纯展示逻辑（无 DOM、无网络、无计时器）。
 *
 * 为什么单独成模块：这层只做「会话快照 → 一行文案 + 动作可见性」的映射，必须能被
 * node 探针确定性地跑；把它塞进 update.js 的 DOM 驱动里就只能靠字符串断言。
 *
 * 注意：本文件**不加** `// @ts-check`，也不在 tsconfig 的显式 allowlist 里 ——
 * 它由 update.js import，只承载纯函数，不直接打 API。
 */
"use strict";

/**
 * 下载进度百分比（0–100 的整数）。
 * @param {number} done
 * @param {number} total
 * @returns {number}
 */
export function updateProgressPercent(done, total) {
  if (!Number.isFinite(done) || !Number.isFinite(total) || total <= 0) return 0;
  if (done <= 0) return 0;
  if (done >= total) return 100;
  return Math.floor((done / total) * 100);
}

/**
 * 失败原因 → 人话。未登记的 reason 一律兜底，绝不回显原始串或 HTTP 状态码。
 * @param {string} reason
 * @returns {string}
 */
export function humanizeUpdateFailure(reason) {
  switch (reason) {
    case "no_space": return "磁盘空间不足，请清理后重试";
    case "checksum_mismatch": return "安装包校验失败，已拒绝安装";
    case "size_mismatch": return "下载不完整，请重试";
    case "network": return "下载失败，请检查网络";
    case "timeout": return "下载超时，请重试";
    case "rate_limited": return "下载请求过于频繁，请稍后重试";
    case "not_found": return "Release 上找不到安装包";
    case "asset_missing": return "Release 缺少该平台的安装包";
    case "checksum_missing": return "Release 缺少校验和，已拒绝下载";
    case "install_failed": return "安装失败，请手动安装";
    case "unsupported": return "当前平台不支持应用内更新";
    case "cancelled": return "已取消更新";
    case "busy": return "已有更新正在进行";
    case "write_failed": return "写入安装包失败，请检查磁盘权限";
    default: return "更新失败，请稍后重试";
  }
}

/**
 * 会话快照 → 展示模型。
 * @param {any} snapshot
 * @returns {{text: string, showCancel: boolean, showRelease: boolean, terminal: boolean}}
 */
export function describeUpdateSnapshot(snapshot) {
  const state = snapshot && typeof snapshot.state === "string" ? snapshot.state : "idle";
  if (state === "downloading") {
    const percent = updateProgressPercent(
      Number(snapshot.downloaded_bytes),
      Number(snapshot.total_bytes),
    );
    return { text: "下载中 " + percent + "%", showCancel: true, showRelease: false, terminal: false };
  }
  if (state === "verifying") {
    return { text: "正在校验安装包…", showCancel: true, showRelease: false, terminal: false };
  }
  if (state === "ready") {
    return { text: "新版本已下载，正在安装…", showCancel: false, showRelease: false, terminal: false };
  }
  if (state === "installing") {
    return { text: "正在安装，应用即将重启…", showCancel: false, showRelease: false, terminal: true };
  }
  if (state === "failed") {
    const reason = snapshot && typeof snapshot.error_reason === "string" ? snapshot.error_reason : "";
    return { text: humanizeUpdateFailure(reason), showCancel: false, showRelease: true, terminal: true };
  }
  return { text: "", showCancel: false, showRelease: false, terminal: false };
}
