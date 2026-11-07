/**
 * motion.js — 动效基建（T2）。
 *
 * 只提供三件事：reduce 检测、stagger 序号、数字计数。
 * 入场动画本身由 CSS `.dl-enter` / `.dl-stagger` 承担（style.css），这里不负责播放。
 * token（时长 / 位移 / 步长）住在 tokens.css，JS 不复制数值。
 */

/** 当前是否处于 `prefers-reduced-motion: reduce`。 */
export function prefersReducedMotion() {
  return typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** 从 :root 读一个毫秒 token；缺失或格式不对时返回 0（调用方落到终态）。 */
function tokenMs(name) {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return raw.endsWith("ms") ? parseFloat(raw) : 0;
}

/**
 * 给 root 的直接子元素分配 `--stagger-index`。
 * 序号封顶在 `cap - 1`，第 cap 项之后不再累加延迟。
 * reduce 下不排队，并清掉旧序号，避免后续重渲染误播。
 *
 * @param {Element} root 承载 `.dl-stagger` 的容器
 * @param {{step?: number, cap?: number}} [options] step 省略时用 CSS token
 * @returns {number} 实际参与错峰的元素数
 */
export function stagger(root, { step, cap = 6 } = {}) {
  if (!root) return 0;
  const items = Array.from(root.children);
  if (prefersReducedMotion()) {
    items.forEach((el) => el.style.removeProperty("--stagger-index"));
    return 0;
  }
  if (step != null) root.style.setProperty("--motion-stagger-step", `${step}ms`);
  items.forEach((el, i) => {
    el.style.setProperty("--stagger-index", String(Math.min(i, cap - 1)));
  });
  return items.length;
}

/**
 * 从当前文本数字递增到 `to`（只播一次，调用方负责只调一次）。
 * reduce 下直接落终态；token 缺失时同样落终态。
 *
 * @param {Element} el 数字容器
 * @param {number} to 目标值
 * @param {{duration?: number, format?: (value: number) => string}} [options]
 */
export function countUp(el, to, { duration, format } = {}) {
  if (!el) return;
  const fmt = format || ((value) => String(Math.round(value)));
  const settle = () => {
    el.textContent = fmt(to);
  };
  if (prefersReducedMotion()) {
    settle();
    return;
  }
  const ms = duration != null ? duration : tokenMs("--motion-count");
  if (!ms) {
    settle();
    return;
  }
  const from = Number(String(el.textContent).replace(/[^\d.-]/g, "")) || 0;
  const start = performance.now();
  const tick = (now) => {
    const progress = Math.min(1, (now - start) / ms);
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = fmt(from + (to - from) * eased);
    if (progress < 1) requestAnimationFrame(tick);
    else settle();
  };
  requestAnimationFrame(tick);
}
