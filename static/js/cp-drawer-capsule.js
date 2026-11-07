/* DeLector - Companion Floating Mascot Capsule Controller
 *
 * 遵循 docs/design-system.md 与 Zero-innerHTML 铁律:
 * 纯原生 DOM 事件监听与坐标计算。
 * 负责全局伴学小萌宠 / 胶囊触发按钮的拖拽、贴边吸附防出界、轻触防误触点击以及窗口自适应重排。
 */
'use strict';

import {
  getCompanionViewport,
  getAvoidPadding,
  collectNoParkRects,
  intersectsAny,
  findSafeDropPosition,
  EDITABLE_SELECTOR
} from './companion-obstacles.js';

/**
 * 初始化全局伴学小萌宠浮动胶囊的拖拽、点击与重排自适应逻辑
 * @param {Object} [options]
 * @param {HTMLElement} [options.element] - 目标胶囊 DOM 节点（缺省按 #companion / .companion 查找）
 * @param {string} [options.selector] - 自定义选择器
 * @param {Function} [options.onClick] - 点击回调函数（当用户仅点击而未产生拖拽位移时触发）
 * @param {Function} [options.onDragStart] - 拖拽开始回调
 * @param {Function} [options.onDragEnd] - 拖拽结束回调
 * @param {Function} [options.onReposition] - 坐标变化回调 ({ left, top })
 * @returns {Object|null} 控制器句柄 { element, reposition, setPosition, destroy }
 */
export function initFloatingCapsule(options) {
  const opts = options || {};

  const capsuleEl =
    opts.element ||
    (opts.selector ? document.querySelector(opts.selector) : null) ||
    document.getElementById(opts.id || 'companion') ||
    document.querySelector('.companion');

  if (!capsuleEl) {
    return null;
  }

  // 避免在同一元素上重复挂载监听器
  if (capsuleEl._floatingCapsuleController) {
    return capsuleEl._floatingCapsuleController;
  }

  let isPointerDown = false;
  let isDragging = false;
  let justDragged = false;
  let startX = 0;
  let startY = 0;
  let initialLeft = 0;
  let initialTop = 0;
  let activePointerId = null;
  let dragObstacles = null;
  let refreshTimer = 0;
  let settleTimer = 0;

  /** 视觉视口：复用 companion-obstacles 的统一实现（含键盘态兜底） */
  function getViewport() {
    return getCompanionViewport();
  }

  /** 胶囊实际缩放系数（移动端 0.88；桌面 1） */
  function getScale() {
    const width = capsuleEl.offsetWidth || 60;
    const rect = capsuleEl.getBoundingClientRect();
    return rect.width ? rect.width / width : 1;
  }

  /** 解析 computed transform-origin（用于把视觉边界换算回布局坐标） */
  function getTransformOrigin() {
    const width = capsuleEl.offsetWidth || 60;
    const height = capsuleEl.offsetHeight || 60;
    const parts = String(window.getComputedStyle(capsuleEl).transformOrigin || '')
      .trim()
      .split(/\s+/);
    const resolve = (token, axisSize) => {
      if (!token || token === 'center') return axisSize / 2;
      if (token === 'left' || token === 'top') return 0;
      if (token === 'right' || token === 'bottom') return axisSize;
      const num = parseFloat(token);
      if (!Number.isFinite(num)) return axisSize / 2;
      return token.endsWith('%') ? (num / 100) * axisSize : num;
    };
    return {
      x: resolve(parts[0], width),
      y: resolve(parts[1] || parts[0], height)
    };
  }

  /** 当前布局坐标（left/top），不受 transform 影响 */
  function getLayoutPosition() {
    const cs = window.getComputedStyle(capsuleEl);
    const left = parseFloat(cs.left);
    const top = parseFloat(cs.top);
    if (Number.isFinite(left) && Number.isFinite(top)) {
      return { left, top };
    }
    const rect = capsuleEl.getBoundingClientRect();
    const scale = getScale();
    const origin = getTransformOrigin();
    return {
      left: rect.left - origin.x * (1 - scale),
      top: rect.top - origin.y * (1 - scale)
    };
  }

  /**
   * 计算并限制坐标在视觉视口以内。
   * 用 offsetWidth/offsetHeight 作为布局尺寸（不受 transform 影响），
   * 再把视觉边界换算回布局坐标：视觉 = 布局 + origin * (1 - scale)。
   */
  function clampPosition(left, top) {
    const width = capsuleEl.offsetWidth || 60;
    const height = capsuleEl.offsetHeight || 60;
    const scale = getScale();
    const origin = getTransformOrigin();
    const vp = getViewport();

    // 缩放使视觉框相对布局框内缩，所以 min 侧要放宽容差
    const minLeft = vp.left - origin.x * (1 - scale);
    const minTop = vp.top - origin.y * (1 - scale);
    const maxLeft = vp.left + vp.width - width * scale - origin.x * (1 - scale);
    const maxTop = vp.top + vp.height - height * scale - origin.y * (1 - scale);

    const clampedLeft = Math.min(Math.max(left, minLeft), Math.max(minLeft, maxLeft));
    const clampedTop = Math.min(Math.max(top, minTop), Math.max(minTop, maxTop));
    return { left: clampedLeft, top: clampedTop };
  }

  /** 胶囊移动后同步气泡位置（气泡求解在 companion.js 内） */
  function notifyBubble() {
    if (window.Companion && typeof window.Companion.repositionBubble === 'function') {
      window.Companion.repositionBubble();
    }
  }

  /** 把布局坐标换算成视觉矩形（缩放 > 1 或 < 1 都适用） */
  function visualRectFor(left, top) {
    const width = capsuleEl.offsetWidth || 60;
    const height = capsuleEl.offsetHeight || 60;
    const scale = getScale();
    const origin = getTransformOrigin();
    return {
      left: left + origin.x * (1 - scale),
      top: top + origin.y * (1 - scale),
      width: width * scale,
      height: height * scale
    };
  }

  /** 直接写入视觉坐标（内部换算回布局坐标），带 260ms 滑入动画 */
  function applyVisualPosition(pos, notify = true) {
    const scale = getScale();
    const origin = getTransformOrigin();
    capsuleEl.style.left = pos.left - origin.x * (1 - scale) + 'px';
    capsuleEl.style.top = pos.top - origin.y * (1 - scale) + 'px';
    capsuleEl.style.right = 'auto';
    capsuleEl.style.bottom = 'auto';

    capsuleEl.classList.add('is-settling');
    if (settleTimer) clearTimeout(settleTimer);
    settleTimer = setTimeout(() => {
      settleTimer = 0;
      capsuleEl.classList.remove('is-settling');
      // P3 状态机据此把 dragging 松手与气泡求解推迟到落点稳定之后
      document.dispatchEvent(new CustomEvent('companion:settle-end'));
    }, 320);

    if (notify) notifyBubble();
  }

  /**
   * 落点/让位统一检查：与任一禁停区相交就滑到最近安全位。
   * 禁停区每次现算（可点击控件 + 编辑区 + dock + 页签 + 浮层），不缓存坐标。
   */
  function settleIfNeeded() {
    if (isPointerDown) return;
    if (!capsuleEl.offsetWidth || !capsuleEl.getClientRects().length) return;

    const vp = getViewport();
    const position = getLayoutPosition();
    const current = visualRectFor(position.left, position.top);
    const obstacles = collectNoParkRects(vp, getAvoidPadding());
    if (!intersectsAny(current, obstacles)) {
      capsuleEl.classList.remove('is-over-no-park');
      // 模态关闭后即使胶囊原位合法，也要让气泡恢复显示
      notifyBubble();
      return;
    }

    const safe = findSafeDropPosition(current, vp, obstacles);
    capsuleEl.classList.remove('is-over-no-park');
    if (safe) applyVisualPosition(safe);
    else notifyBubble();
  }

  /** 低频事件合并：键盘动画 / 视图切换会连续触发，统一 120ms 后再求解 */
  function scheduleRefresh(delay) {
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => {
      refreshTimer = 0;
      settleIfNeeded();
    }, typeof delay === 'number' ? delay : 120);
  }

  function onFocusChange(e) {
    const target = e.target;
    const editable =
      target && typeof target.closest === 'function' ? target.closest(EDITABLE_SELECTOR) : null;
    if (editable) {
      // 编辑态让位：等键盘/滚动把编辑区推到最终位置后再校准
      scheduleRefresh(160);
    } else if (e.type === 'focusout') {
      scheduleRefresh(240);
    }
  }

  /** 仅覆盖导航/页签切换（视图渲染后再校准一次），不在任意点击上跑避让 */
  function onNavIntent(e) {
    const target = e.target;
    if (!target || typeof target.closest !== 'function') return;
    if (target.closest('.dock-item, .mobile-nav-btn, .nav-tab, #mobile-bottom-nav, #nav')) {
      scheduleRefresh(280);
    }
  }

  /** 将胶囊定位到指定坐标，或在视口内就地修正 */
  function reposition(x, y) {
    const current = getLayoutPosition();
    const targetLeft = typeof x === 'number' ? x : current.left;
    const targetTop = typeof y === 'number' ? y : current.top;

    const clamped = clampPosition(targetLeft, targetTop);
    capsuleEl.style.left = clamped.left + 'px';
    capsuleEl.style.top = clamped.top + 'px';
    capsuleEl.style.right = 'auto';
    capsuleEl.style.bottom = 'auto';

    if (typeof opts.onReposition === 'function') {
      opts.onReposition(clamped);
    }
    notifyBubble();
  }

  function onPointerDown(e) {
    // 忽略右键或非主按键
    if (e.button !== undefined && e.button !== 0) return;

    // 若点击源是内部展开面板、表单或按钮，则不启动胶囊本体拖拽
    const target = e.target;
    if (
      target &&
      typeof target.closest === 'function' &&
      (target.closest('input') ||
        target.closest('button.mascot-choice-btn') ||
        target.closest('.companion-panel'))
    ) {
      return;
    }

    isPointerDown = true;
    isDragging = false;
    startX = e.clientX;
    startY = e.clientY;

    const current = getLayoutPosition();
    initialLeft = current.left;
    initialTop = current.top;
    activePointerId = e.pointerId;

    // 拖拽期禁停区只在按下时收集一次；move 里复用，避免每帧遍历 DOM
    dragObstacles = collectNoParkRects(getViewport(), getAvoidPadding());

    // 优先在真实触控 target 上执行 pointerCapture，避免容器 pointer-events: none 造成拒绝
    const captureEl =
      target && typeof target.setPointerCapture === 'function'
        ? target
        : typeof capsuleEl.setPointerCapture === 'function'
          ? capsuleEl
          : null;
    if (captureEl && e.pointerId != null) {
      try {
        captureEl.setPointerCapture(e.pointerId);
      } catch (_) {
        // 容错静默
      }
    }

    // 全局挂载 move 与 up，确保移动端手指滑动超出 72px 元素时不丢弃事件
    window.addEventListener('pointermove', onPointerMove, { passive: false });
    window.addEventListener('pointerup', onPointerUp, { passive: false });
    window.addEventListener('pointercancel', onPointerUp, { passive: false });
  }

  function onPointerMove(e) {
    if (!isPointerDown) return;
    if (activePointerId != null && e.pointerId !== activePointerId) return;

    const dx = e.clientX - startX;
    const dy = e.clientY - startY;

    if (!isDragging && Math.hypot(dx, dy) > 5) {
      isDragging = true;
      capsuleEl.classList.add('is-dragging');
      if (typeof opts.onDragStart === 'function') {
        opts.onDragStart(e);
      }
    }

    if (isDragging) {
      if (e.cancelable) {
        e.preventDefault();
      }
      const currentLeft = initialLeft + dx;
      const currentTop = initialTop + dy;
      const clamped = clampPosition(currentLeft, currentTop);

      capsuleEl.style.left = clamped.left + 'px';
      capsuleEl.style.top = clamped.top + 'px';
      capsuleEl.style.right = 'auto';
      capsuleEl.style.bottom = 'auto';

      // 拖拽期反馈：悬在禁停区上时半透明 + 虚线描边（松手会滑到最近安全位）
      const hoveringNoPark =
        dragObstacles &&
        intersectsAny(visualRectFor(clamped.left, clamped.top), dragObstacles);
      capsuleEl.classList.toggle('is-over-no-park', Boolean(hoveringNoPark));

      notifyBubble();
    }
  }

  function onPointerUp(e) {
    if (!isPointerDown) return;
    if (activePointerId != null && e.pointerId !== activePointerId) return;

    window.removeEventListener('pointermove', onPointerMove);
    window.removeEventListener('pointerup', onPointerUp);
    window.removeEventListener('pointercancel', onPointerUp);

    isPointerDown = false;

    const captureEl =
      e.target && typeof e.target.releasePointerCapture === 'function'
        ? e.target
        : typeof capsuleEl.releasePointerCapture === 'function'
          ? capsuleEl
          : null;
    if (captureEl && activePointerId != null) {
      try {
        captureEl.releasePointerCapture(activePointerId);
      } catch (_) {
        // 容错静默
      }
    }
    activePointerId = null;

    if (isDragging) {
      isDragging = false;
      capsuleEl.classList.remove('is-dragging');
      capsuleEl.classList.remove('is-over-no-park');
      dragObstacles = null;

      const pos = getLayoutPosition();

      if (typeof opts.onDragEnd === 'function') {
        opts.onDragEnd(pos);
      }
      if (typeof opts.onReposition === 'function') {
        opts.onReposition(pos);
      }

      // 落点避让：压住禁停区则滑到最近安全位（不硬禁止，也不回弹到原位）
      settleIfNeeded();

      // 防误触：移动端手势释放后会有最高 300ms 延迟合成 click 事件，统一屏蔽
      justDragged = true;
      if (window.Companion && typeof window.Companion._suppressClick === 'function') {
        window.Companion._suppressClick(400);
      }
      setTimeout(() => {
        justDragged = false;
      }, 350);
    } else {
      // 纯点击
      dragObstacles = null;
      if (typeof opts.onClick === 'function') {
        opts.onClick(e);
      }
    }
  }

  function onClick(e) {
    if (justDragged) {
      e.stopPropagation();
      if (typeof e.stopImmediatePropagation === 'function') {
        e.stopImmediatePropagation();
      }
      e.preventDefault();
    }
  }

  function onResize() {
    // 视口尺寸变化（含软键盘弹出导致的视觉视口变矮）时重新贴边校准，
    // 再按新的可视区让位到禁停区之外。
    reposition();
    scheduleRefresh(120);
  }

  // 绑定事件
  capsuleEl.addEventListener('pointerdown', onPointerDown, { passive: true });
  capsuleEl.addEventListener('click', onClick, true);
  window.addEventListener('resize', onResize);
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', onResize);
    window.visualViewport.addEventListener('scroll', onResize);
  }
  document.addEventListener('focusin', onFocusChange, true);
  document.addEventListener('focusout', onFocusChange, true);
  document.addEventListener('click', onNavIntent, true);

  // 写作页 sheet / 底部 dock / 抽屉的开合会改变可停放区域，监听 class 变化即可
  let observer = null;
  if (typeof MutationObserver === 'function') {
    observer = new MutationObserver(() => scheduleRefresh(120));
    ['writer-panel', 'writer-mobile-panel-sheet', 'mobile-bottom-nav', 'drawer'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) {
        observer.observe(el, {
          attributes: true,
          attributeFilter: ['class', 'style', 'hidden']
        });
      }
    });
  }

  // 首帧后校准一次（默认右下角可能正好压在 dock 上）
  scheduleRefresh(180);

  function destroy() {
    capsuleEl.removeEventListener('pointerdown', onPointerDown);
    window.removeEventListener('pointermove', onPointerMove);
    window.removeEventListener('pointerup', onPointerUp);
    window.removeEventListener('pointercancel', onPointerUp);
    capsuleEl.removeEventListener('click', onClick, true);
    window.removeEventListener('resize', onResize);
    if (window.visualViewport) {
      window.visualViewport.removeEventListener('resize', onResize);
      window.visualViewport.removeEventListener('scroll', onResize);
    }
    document.removeEventListener('focusin', onFocusChange, true);
    document.removeEventListener('focusout', onFocusChange, true);
    document.removeEventListener('click', onNavIntent, true);
    if (observer) observer.disconnect();
    if (refreshTimer) clearTimeout(refreshTimer);
    if (settleTimer) clearTimeout(settleTimer);
    delete capsuleEl._floatingCapsuleController;
  }

  const controller = {
    element: capsuleEl,
    reposition,
    setPosition: reposition,
    settle: settleIfNeeded,
    refresh: settleIfNeeded,
    /** 供气泡求解器做联合让位：移动到指定视觉坐标，不再反向通知气泡 */
    moveToVisual: (pos) => applyVisualPosition(pos, false),
    destroy
  };

  capsuleEl._floatingCapsuleController = controller;
  return controller;
}
