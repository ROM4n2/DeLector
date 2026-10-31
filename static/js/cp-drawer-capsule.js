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

  /** 计算并限制坐标在可视视口以内 */
  function clampPosition(left, top) {
    const rect = capsuleEl.getBoundingClientRect();
    const width = rect.width || 60;
    const height = rect.height || 60;
    const maxLeft = Math.max(0, window.innerWidth - width);
    const maxTop = Math.max(0, window.innerHeight - height);

    const clampedLeft = Math.min(Math.max(0, left), maxLeft);
    const clampedTop = Math.min(Math.max(0, top), maxTop);
    return { left: clampedLeft, top: clampedTop };
  }

  /** 将胶囊定位到指定坐标，或在视口内就地修正 */
  function reposition(x, y) {
    const rect = capsuleEl.getBoundingClientRect();
    let targetLeft = typeof x === 'number' ? x : rect.left;
    let targetTop = typeof y === 'number' ? y : rect.top;

    const clamped = clampPosition(targetLeft, targetTop);
    capsuleEl.style.left = clamped.left + 'px';
    capsuleEl.style.top = clamped.top + 'px';
    capsuleEl.style.right = 'auto';
    capsuleEl.style.bottom = 'auto';

    if (typeof opts.onReposition === 'function') {
      opts.onReposition(clamped);
    }
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

    const rect = capsuleEl.getBoundingClientRect();
    initialLeft = rect.left;
    initialTop = rect.top;
    activePointerId = e.pointerId;

    if (typeof capsuleEl.setPointerCapture === 'function' && e.pointerId != null) {
      try {
        capsuleEl.setPointerCapture(e.pointerId);
      } catch (_) {
        // 容错静默
      }
    }
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
      e.preventDefault();
      const currentLeft = initialLeft + dx;
      const currentTop = initialTop + dy;
      const clamped = clampPosition(currentLeft, currentTop);

      capsuleEl.style.left = clamped.left + 'px';
      capsuleEl.style.top = clamped.top + 'px';
      capsuleEl.style.right = 'auto';
      capsuleEl.style.bottom = 'auto';
    }
  }

  function onPointerUp(e) {
    if (!isPointerDown) return;
    if (activePointerId != null && e.pointerId !== activePointerId) return;

    isPointerDown = false;

    if (typeof capsuleEl.releasePointerCapture === 'function' && activePointerId != null) {
      try {
        capsuleEl.releasePointerCapture(activePointerId);
      } catch (_) {
        // 容错静默
      }
    }
    activePointerId = null;

    if (isDragging) {
      isDragging = false;
      capsuleEl.classList.remove('is-dragging');

      const rect = capsuleEl.getBoundingClientRect();
      const pos = { left: rect.left, top: rect.top };

      if (typeof opts.onDragEnd === 'function') {
        opts.onDragEnd(pos);
      }
      if (typeof opts.onReposition === 'function') {
        opts.onReposition(pos);
      }

      // 防误触：拖拽释放后的短时间内屏蔽 click 事件触发
      justDragged = true;
      setTimeout(() => {
        justDragged = false;
      }, 120);
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
      e.preventDefault();
    }
  }

  function onResize() {
    // 视口尺寸变化时重新贴边校准
    reposition();
  }

  // 绑定事件
  capsuleEl.addEventListener('pointerdown', onPointerDown);
  capsuleEl.addEventListener('pointermove', onPointerMove);
  capsuleEl.addEventListener('pointerup', onPointerUp);
  capsuleEl.addEventListener('pointercancel', onPointerUp);
  capsuleEl.addEventListener('click', onClick, true);
  window.addEventListener('resize', onResize);

  function destroy() {
    capsuleEl.removeEventListener('pointerdown', onPointerDown);
    capsuleEl.removeEventListener('pointermove', onPointerMove);
    capsuleEl.removeEventListener('pointerup', onPointerUp);
    capsuleEl.removeEventListener('pointercancel', onPointerUp);
    capsuleEl.removeEventListener('click', onClick, true);
    window.removeEventListener('resize', onResize);
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
