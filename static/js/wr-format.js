/* DeLector - Writing Desk: 纯格式化 / 领域文案层（L1 纯层）
 *
 * 分层契约（由 tools/check_frontend_layers.py 机械强制；见
 * docs/plans/2026-10-19-writer-js-modularization.md Task 2）：
 *   MUST NOT 触碰 DOM（document / window / navigator / localStorage /
 *   getElementById / querySelector / innerHTML / addEventListener）；
 *   MUST NOT 发网络请求（fetch / api / XMLHttpRequest）；
 *   MUST NOT 弹用户提示（notify / alert / confirm）；
 *   MUST NOT 用计时器（setTimeout / setInterval）；
 *   MUST NOT 有顶层 `let`（无可变模块状态）。唯一允许的 import 是 ./core.js 的 esc()。
 *
 * 为什么单独成层：这几样东西原先和 DOM 渲染、网络调用挤在 writer.js 的同一个模块
 * 作用域里，纯函数既没法单测、也没法在不拖进 DOM 的前提下复用。层边界一旦由机械闸
 * 钉住，往后谁往这里塞 document / fetch 都会当场变红，而不是靠人记得。
 */
'use strict';

import { esc } from './core.js';

// ── Error Type Labels & Badges ──────────────────────────────────────────────
export const ERROR_TYPE_LABELS = {
  artikel: '冠词 / 性数格一致',
  kasus: '介词支配格错误',
  praeposition: '固定介词搭配',
  andere: '语法与拼写规范'
};

export function getErrorTypeLabel(type) {
  return ERROR_TYPE_LABELS[type] || '语法考点';
}

// ── Sidebar Tab Navigation (v4.2.0) ─────────────────────────────────────────
export const WRITER_TABS = ['diag', 'problems', 'versions'];

// ── Word-level LCS Diff Helper for Agent Review ─────────────────────────────
export function renderWordDiff(oldSent, newSent) {
  if (!oldSent && !newSent) return { oldHtml: '', newHtml: '' };
  if (!oldSent) {
    return {
      oldHtml: '<div class="diff-empty">(无对应原句 / 新增内容)</div>',
      newHtml: `<div class="diff-sent diff-ins-block"><span class="diff-prefix">+</span>${esc(newSent)}</div>`
    };
  }
  if (!newSent) {
    return {
      oldHtml: `<div class="diff-sent diff-del-block"><span class="diff-prefix">-</span>${esc(oldSent)}</div>`,
      newHtml: '<div class="diff-empty">(建议删除此句)</div>'
    };
  }

  const w1 = oldSent.split(/(\s+|[.,!?;:„"“'«»()—–-])/).filter(Boolean);
  const w2 = newSent.split(/(\s+|[.,!?;:„"“'«»()—–-])/).filter(Boolean);
  const n = w1.length;
  const m = w2.length;

  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < m; j++) {
      if (w1[i] === w2[j]) {
        dp[i + 1][j + 1] = dp[i][j] + 1;
      } else {
        dp[i + 1][j + 1] = dp[i][j] > dp[i][j + 1] ? dp[i][j] : dp[i][j + 1];
      }
    }
  }

  let i = n;
  let j = m;
  const out1 = [];
  const out2 = [];
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && w1[i - 1] === w2[j - 1]) {
      out1.push(esc(w1[i - 1]));
      out2.push(esc(w2[j - 1]));
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      out2.push(`<mark class="diff-token-ins">${esc(w2[j - 1])}</mark>`);
      j--;
    } else if (i > 0 && (j === 0 || dp[i][j - 1] < dp[i - 1][j])) {
      out1.push(`<mark class="diff-token-del">${esc(w1[i - 1])}</mark>`);
      i--;
    }
  }

  out1.reverse();
  out2.reverse();
  return {
    oldHtml: `<div class="diff-sent"><span class="diff-prefix">-</span>${out1.join('')}</div>`,
    newHtml: `<div class="diff-sent"><span class="diff-prefix">+</span>${out2.join('')}</div>`
  };
}

// ── AI 润色：未收敛原因码 → 中文人话 ────────────────────────────────────────
// 键集合 MUST 与后端 `polish_loop.REASONS` **同构**（外加端点层的 no_api_key）：
// 由 tests/test_server_ai_polish.py::test_frontend_polish_reason_copy_covers_every_reason_code
// 钉住 —— 后端加原因码而前端漏配文案，那条用例立刻红。
// `ok` 一档收敛成功时不会弹 toast（那时直接开逐 hunk 审查面板），留着只为与
// REASONS 同构，免得哪天有人判 `converged === false` 时拿到 undefined。
export const POLISH_REASON_COPY = {
  ok: '润色完成：已通过 A1 硬规则检查。',
  no_api_key: '尚未配置 DeepSeek API Key，本次未改动原文。请在「设置」里填写后再润色。',
  no_improvement: 'AI 改了几轮仍没能减少硬性错误，已保留更接近原文的一版。',
  turn_limit: '润色轮次用尽仍未达标，已保留当前最优一版。',
  token_budget: '本次润色超出预算上限已中止，已保留当前最优一版。',
  deadline: '润色超时已中止，已保留当前最优一版。',
  judge_unreliable: '自动裁判连续两轮判定相同，已停止改动并保留当前最优一版。',
  judge_error: '自动裁判本次不可用，未套用 AI 的改动。',
  cancelled: '你中止了本次润色，已保留当前最优一版。'
};

export function polishReasonText(reason) {
  return POLISH_REASON_COPY[reason] || ('润色未收敛：' + (reason || '未知原因'));
}
