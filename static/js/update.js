// @ts-check
/* DeLector - 顶栏「版本更新 chip」的唯一驱动源（Task 5）。
 *
 * 端点契约：GET /api/update/check（同源）返回恰 7 键
 *   {current, latest, has_update, page_url, checked_at, cached, error_reason}
 * has_update 三态（true | false | null），null ⇔ error_reason 非空（后端已明确「没查到」）。
 *
 * 可见性红线：只有 has_update === true 才允许改变顶栏。
 * 「无新版 / 拿不准(null) / 请求异常」三种情况一律**零可见变化** —— 顶栏那句
 * 「System · vX.Y.Z」是用户判断「前端资源刷没刷新」的自证指标（v4.4.5 漏 bump 出过事故），
 * 更新状态只由本模块的 chip 承载，绝不污染它。
 *
 * 探针同步驱动依赖：initUpdateCheck 刻意用**普通可选参数**（非条件编译分支）注入
 * fetchImpl / setTimeoutFn / delayMs，从而可在 node:vm 里确定性复现四种响应路径。
 */
"use strict";

import { esc } from "./core.js";

export function initUpdateCheck(options = {}) {
  // ── 依赖注入（探针用；浏览器走默认值）──────────────────────────────────
  const delayMs = options.delayMs == null ? 3000 : options.delayMs;
  const doFetch = options.fetchImpl || globalThis.fetch;
  const schedule = options.setTimeoutFn || globalThis.setTimeout;
  const NOTICE_MS = 3000;

  // 端点路径内联（不抽标量常量），使本函数自足、可被探针按括号配对整段切片。
  const chip = document.getElementById("update-chip");
  const trigger = document.getElementById("topbar-system");
  if (!chip || typeof doFetch !== "function" || typeof schedule !== "function") return;

  // title 是手动入口的非侵入式状态反馈，不改写顶栏版本自证文本。
  function setTriggerTitle(text) {
    if (!trigger || typeof trigger.setAttribute !== "function") return;
    trigger.setAttribute("title", text);
  }

  // 失败原因 → 人话。禁止直出「HTTP 403」/「fetch failed」/「TypeError」之类原始文本；
  // 未登记的 reason 一律兜底，绝不回显原始串（回显等于把实现细节漏给用户）。
  function humanize(reason) {
    switch (reason) {
      case "network": return "连不上 GitHub，请稍后重试";
      case "http": return "GitHub 暂时不可用，请稍后重试";
      case "timeout": return "连接超时，请稍后重试";
      case "rate_limited": return "请求过于频繁，请稍后重试";
      case "not_found": return "GitHub 上暂无发行信息，请稍后重试";
      case "parse": return "响应解析失败，请稍后重试";
      default: return "检查更新失败，请稍后重试";
    }
  }

  // 所有动态值（版本号 / 链接 / 文案）都先经 esc() 再写 innerHTML：
  // esc() 同时转义引号与 &，故既能挡文本注入，也能挡 href 的属性注入（引号越狱）。
  function showChip(latest, pageUrl) {
    chip.innerHTML =
      '<a class="update-chip-link" href="' + esc(pageUrl) +
      '" target="_blank" rel="noopener noreferrer">可更新 v' + esc(latest) + "</a>";
    chip.hidden = false;
  }

  // 手动检查的短暂反馈：显示一句人话，约 3s 后清空（一次性 setTimeout，绝不轮询）。
  function showNotice(text) {
    chip.innerHTML = esc(text);
    chip.hidden = false;
    schedule(function () {
      chip.innerHTML = "";
      chip.hidden = true;
    }, NOTICE_MS);
  }

  // manual=false（自动）：非「有新版」一律不动 DOM（零可见变化）。
  // manual=true（点顶栏 System 版本号）：把结论以人话回显到 chip。
  async function runCheck(manual) {
    if (manual) setTriggerTitle("正在检查更新…");
    let hasUpdate = null;
    let latest = "";
    let pageUrl = "";
    let reason = "";
    try {
      const resp = await doFetch("/api/update/check", {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!resp || !resp.ok) {
        reason = "http";
      } else {
        const data = await resp.json();
        if (data && data.has_update === true) { hasUpdate = true; }
        else if (data && data.has_update === false) { hasUpdate = false; }
        else { hasUpdate = null; }
        latest = data ? data.latest : "";
        pageUrl = data ? data.page_url : "";
        reason = data && data.error_reason ? data.error_reason : "";
      }
    } catch (e) {
      hasUpdate = null;
      reason = reason || "network";
    }

    if (manual && hasUpdate === true) {
      setTriggerTitle("发现新版本，点击重新检查");
    }
    if (hasUpdate === true) {
      showChip(latest, pageUrl);
      return;
    }
    if (!manual) return;                 // 自动路径：零可见变化
    if (hasUpdate === false) {
      showNotice("已是最新");
      setTriggerTitle("已是最新，点击重新检查");
      return;
    }
    const failureMessage = humanize(reason);
    showNotice(failureMessage);
    setTriggerTitle(failureMessage + "，点击重试");
  }

  // 点击与键盘共用同一入口，避免两条交互路径的检查语义漂移。
  function runManualCheck() {
    runCheck(true);
  }

  function handleTriggerKeydown(event) {
    if (!event || (event.key !== "Enter" && event.key !== " ")) return;
    if (event.key === " ") event.preventDefault();
    runManualCheck();
  }

  if (trigger && typeof trigger.addEventListener === "function") {
    trigger.addEventListener("click", runManualCheck);
    trigger.addEventListener("keydown", handleTriggerKeydown);
  }

  // 一次性延迟检查（禁止轮询式定时器：会持续打后端且毫无意义）。
  schedule(function () { runCheck(false); }, delayMs);
}
