/* DeLector - Companion No-Park Zones & Safe Placement
 *
 * 禁停区完全由运行时 DOM 矩形推导：不写死任何坐标，也不维护静态坐标表。
 * 供 cp-drawer-capsule.js（胶囊落点）与 companion.js（气泡四侧求解）共用。
 */
'use strict';

/** 需要避让的元素：可点击控件、编辑/正文关键区、底部 dock、页签、高层浮层 */
const NO_PARK_SELECTOR = [
  'button',
  'a[href]',
  'input',
  'textarea',
  'select',
  'summary',
  '[role="button"]',
  '[role="tab"]',
  '[role="textbox"]',
  '[contenteditable=""]',
  '[contenteditable="true"]',
  '#nav',
  '#mobile-bottom-nav',
  '#ide-editor',
  '#writer-title',
  '#writer-panel',
  '#drawer',
  '[role="dialog"]',
  '.modal'
].join(',');

/** 编辑态判定：这些元素获得焦点时，桌宠必须让出它们所在的位置 */
export const EDITABLE_SELECTOR = [
  'input',
  'textarea',
  'select',
  '[contenteditable=""]',
  '[contenteditable="true"]',
  '[role="textbox"]',
  '#ide-editor',
  '#writer-title'
].join(',');

/**
 * 视觉视口（软键盘 / 缩放后真正可见的区域）。
 * 复用写作页已有的 --writer-vvh / --writer-keyboard-inset：
 * - 有 visualViewport 时以它为准；
 * - 老 WebView 没有 visualViewport 时，用 布局高度 − 键盘遮挡 作为可见高度。
 */
export function getCompanionViewport() {
  const vv = window.visualViewport;
  let left = 0;
  let top = 0;
  let width = document.documentElement.clientWidth || window.innerWidth;
  let height = document.documentElement.clientHeight || window.innerHeight;

  if (vv && vv.width > 0 && vv.height > 0) {
    left = vv.offsetLeft || 0;
    top = vv.offsetTop || 0;
    width = vv.width;
    height = vv.height;
  } else {
    const cs = getComputedStyle(document.documentElement);
    const inset = parseFloat(cs.getPropertyValue('--writer-keyboard-inset'));
    if (Number.isFinite(inset) && inset > 0) {
      height = Math.max(0, height - inset);
    }
  }

  return { left, top, right: left + width, bottom: top + height, width, height };
}

/** 移动端 8px / 桌面 12px 的避让外扩 */
export function getAvoidPadding() {
  return window.matchMedia('(max-width: 1024px)').matches ? 8 : 12;
}

function isEligible(el) {
  if (!el || el.nodeType !== 1) return false;
  if (el.closest('.companion')) return false; // 桌宠自身
  if (el.closest('[aria-hidden="true"]')) return false; // 纯装饰
  if (el.disabled) return false;
  if (!el.getClientRects().length) return false;
  const cs = getComputedStyle(el);
  if (cs.display === 'none' || cs.visibility === 'hidden') return false;
  if (parseFloat(cs.opacity) === 0) return false;
  if (cs.pointerEvents === 'none') return false;
  return true;
}

/**
 * 收集当前可见禁停区（视觉坐标，已外扩 pad 并裁到视觉视口）。
 * 只做一次 querySelectorAll + getBoundingClientRect，调用点均为低频事件。
 */
export function collectNoParkRects(viewport, pad) {
  const vp = viewport || getCompanionViewport();
  const margin = typeof pad === 'number' ? pad : getAvoidPadding();
  const rects = [];

  document.querySelectorAll(NO_PARK_SELECTOR).forEach((el) => {
    if (!isEligible(el)) return;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;

    const left = Math.max(vp.left, r.left) - margin;
    const top = Math.max(vp.top, r.top) - margin;
    const right = Math.min(vp.right, r.right) + margin;
    const bottom = Math.min(vp.bottom, r.bottom) + margin;
    if (right <= left || bottom <= top) return;
    if (right <= vp.left || bottom <= vp.top || left >= vp.right || top >= vp.bottom) return;

    // 被已有大矩形完整包含的（如 dock 里的按钮）不重复登记
    const contained = rects.some(
      (o) => left >= o.left && top >= o.top && right <= o.right && bottom <= o.bottom
    );
    if (!contained) rects.push({ left, top, right, bottom });
  });

  return rects;
}

/** 矩形是否与任一禁停区相交（矩形用视觉坐标） */
export function intersectsAny(rect, obstacles) {
  const left = rect.left;
  const top = rect.top;
  const right = rect.left + rect.width;
  const bottom = rect.top + rect.height;
  return obstacles.some(
    (o) => left < o.right && right > o.left && top < o.bottom && bottom > o.top
  );
}

/**
 * 求离 current 最近的安全停放位（视觉坐标）。
 * 候选来自「每个障碍的上/下/左/右」+ 四个视口角，按距离从近到远取第一个完整可见且不相交的位置。
 */
export function findSafeDropPosition(current, viewport, obstacles) {
  const vp = viewport || getCompanionViewport();
  const w = current.width;
  const h = current.height;
  const margin = getAvoidPadding();

  const clampX = (x) => Math.min(Math.max(x, vp.left + margin), Math.max(vp.left + margin, vp.right - margin - w));
  const clampY = (y) => Math.min(Math.max(y, vp.top + margin), Math.max(vp.top + margin, vp.bottom - margin - h));

  const inside = (l, t) =>
    l >= vp.left + margin - 0.5 &&
    t >= vp.top + margin - 0.5 &&
    l + w <= vp.right - margin + 0.5 &&
    t + h <= vp.bottom - margin + 0.5;

  const free = (l, t) => inside(l, t) && !intersectsAny({ left: l, top: t, width: w, height: h }, obstacles);

  const startLeft = clampX(current.left);
  const startTop = clampY(current.top);
  if (free(startLeft, startTop)) return { left: startLeft, top: startTop };

  const cx = current.left + w / 2;
  const cy = current.top + h / 2;
  const nearby = obstacles
    .map((o) => ({
      o,
      d: (o.left + o.right) / 2 - cx,
      e: (o.top + o.bottom) / 2 - cy
    }))
    .sort((a, b) => a.d * a.d + a.e * a.e - (b.d * b.d + b.e * b.e))
    .slice(0, 60);

  for (const { o } of nearby) {
    // 以障碍四边为基准，尽量保持当前另一轴不动
    const candidates = [
      { left: startLeft, top: o.top - h },
      { left: startLeft, top: o.bottom },
      { left: o.left - w, top: startTop },
      { left: o.right, top: startTop },
      { left: o.left, top: o.top - h },
      { left: o.right - w, top: o.top - h },
      { left: o.left, top: o.bottom },
      { left: o.right - w, top: o.bottom }
    ];
    for (const c of candidates) {
      const l = clampX(c.left);
      const t = clampY(c.top);
      if (free(l, t)) return { left: l, top: t };
    }
  }

  // 兜底：四角里离当前最近的安全角
  const corners = [
    { left: vp.left + margin, top: vp.top + margin },
    { left: vp.right - margin - w, top: vp.top + margin },
    { left: vp.left + margin, top: vp.bottom - margin - h },
    { left: vp.right - margin - w, top: vp.bottom - margin - h }
  ]
    .map((c) => ({ left: clampX(c.left), top: clampY(c.top) }))
    .sort(
      (a, b) =>
        (a.left - current.left) ** 2 + (a.top - current.top) ** 2 -
        ((b.left - current.left) ** 2 + (b.top - current.top) ** 2)
    );

  for (const c of corners) {
    if (free(c.left, c.top)) return c;
  }
  return null;
}
