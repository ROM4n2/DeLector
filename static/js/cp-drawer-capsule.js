/* DeLector - Companion Floating Mascot Capsule Controller
 *
 * 遵循 docs/design-system.md 与 Zero-innerHTML 铁律:
 * 纯原生 DOM 事件监听与坐标计算。
 * 负责全局伴学小萌宠 / 胶囊触发按钮的拖拽、贴边吸附防出界、轻触防误触点击以及窗口自适应重排。
 */
'use strict';

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

  /** 视觉视口：软键盘弹出 / 双指缩放后真正可见的区域 */
  function getViewport() {
    const vv = window.visualViewport;
    if (vv && vv.width > 0 && vv.height > 0) {
      return {
        left: vv.offsetLeft || 0,
        top: vv.offsetTop || 0,
        width: vv.width,
        height: vv.height
      };
    }
    return {
      left: 0,
      top: 0,
      width: document.documentElement.clientWidth || window.innerWidth,
      height: document.documentElement.clientHeight || window.innerHeight
    };
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

      const pos = getLayoutPosition();

      if (typeof opts.onDragEnd === 'function') {
        opts.onDragEnd(pos);
      }
      if (typeof opts.onReposition === 'function') {
        opts.onReposition(pos);
      }

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
    // 视口尺寸变化（含软键盘弹出导致的视觉视口变矮）时重新贴边校准
    reposition();
  }

  // 绑定事件
  capsuleEl.addEventListener('pointerdown', onPointerDown, { passive: true });
  capsuleEl.addEventListener('click', onClick, true);
  window.addEventListener('resize', onResize);
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', onResize);
    window.visualViewport.addEventListener('scroll', onResize);
  }

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
    delete capsuleEl._floatingCapsuleController;
  }

  const controller = {
    element: capsuleEl,
    reposition,
    setPosition: reposition,
    destroy
  };

  capsuleEl._floatingCapsuleController = controller;
  return controller;
}
