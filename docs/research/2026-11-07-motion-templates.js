// ─────────────────────────────────────────────────────────────
// DeLector motion helpers
// 无依赖，ESM。配合 motion-templates.css 使用。
// 原则：只播一次；系统开启「减少动态」时直接落到终态。
// ─────────────────────────────────────────────────────────────

export function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * 列表逐项入场。
 * 什么时候用：一次渲染 3–6 个卡片/结果，且用户还没滚动过它们。
 * 什么时候别用：滚动中追加、分页加载、超过 6 项、正文列表。
 *
 * CSS 里已有 nth-child 兜底；这个函数只负责「重播一次」和
 * 给动态生成的列表补 --stagger-index。
 */
export function stagger(root, { step = 40, cap = 6 } = {}) {
  if (!root) return;
  const items = Array.from(root.children);
  items.forEach((el, i) => {
    el.style.setProperty('--stagger-index', String(Math.min(i, cap - 1)));
    // 强制重排，让同一节点二次进入时动画重新播放
    el.style.animation = 'none';
    void el.offsetWidth;
    el.style.animation = '';
  });
  root.style.setProperty('--stagger-step', `${step}ms`);
}

/**
 * 数字从 0 滚到目标值。
 * 什么时候用：统计页首次进入、结果总数第一次出现。
 * 什么时候别用：实时变化的数据、金额、表格单元格。
 *
 * 注意：不要给计数元素加 aria-live，否则每帧都会被朗读；
 * 用 aria-label 一次性给出最终值。
 */
export function countUp(el, to, { duration = 520, format } = {}) {
  if (!el) return () => {};
  const fmt = format || ((n) => String(Math.round(n)));
  el.setAttribute('aria-label', fmt(to));

  if (prefersReducedMotion()) {
    el.textContent = fmt(to);
    return () => {};
  }

  el.textContent = fmt(0);
  let raf = 0;
  let start = 0;

  const tick = (t) => {
    if (!start) start = t;
    const p = Math.min(1, (t - start) / duration);
    const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic，不做回弹
    el.textContent = fmt(to * eased);
    if (p < 1) raf = requestAnimationFrame(tick);
  };

  raf = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(raf);
}

/**
 * 元素首次进入视口时加一次性入场类。
 * 什么时候用：长页面里确实需要「滚到才出现」的卡片。
 * 什么时候别用：首屏内容（会闪）、正文段落、需要 SEO 可读的文本。
 */
export function revealOnce(root, { threshold = 0.15, className = 'dl-content-enter' } = {}) {
  if (!root) return () => {};
  if (!('IntersectionObserver' in window)) {
    root.classList.add(className);
    return () => {};
  }
  const io = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add(className);
        io.unobserve(entry.target);
      }
    },
    { threshold }
  );
  io.observe(root);
  return () => io.disconnect();
}
