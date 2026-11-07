/* DeLector - Companion Lifecycle State Machine (L1 Pure Layer)
 *
 * 伴读桌宠生机状态机（依据 docs/plans/2026-11-07-companion-p3-state-machine-design.md）。
 *
 * 契约：
 *   - 状态是「条件」的纯函数，事件只改条件，禁止在事件回调里直接写状态；
 *   - 本模块 MUST NOT 触碰 DOM / 网络 / 计时器 / 用户提示，MUST NOT import 任何模块；
 *   - 唯一真相由调用方写到 `#companion[data-state]`，本模块不持有运行时状态。
 */
'use strict';

/** 状态名是 CSS 选择器的一部分，新增状态必须同步 style.css 的 P3 分区。 */
export const LIFECYCLE_STATES = Object.freeze([
  'idle',
  'thinking',
  'acting',
  'speaking',
  'waiting',
  'dragging',
  'sleeping',
  'error'
]);

const STATE_LABELS = Object.freeze({
  idle: '待机',
  thinking: '思考中',
  acting: '执行工具',
  speaking: '说话',
  waiting: '等待确认',
  dragging: '拖拽中',
  sleeping: '休息',
  error: '出错了'
});

/**
 * 条件容器。所有字段都是「当前是否成立」，不是一次性事件。
 * `sleeping` 预留给 P3.2；MVP 恒为 false。
 */
export function createLifecycleConditions(overrides) {
  return {
    dragging: false,
    errorLatched: false,
    proposalPending: false,
    turnInFlight: false,
    toolActive: false,
    bubbleVisible: false,
    sleeping: false,
    ...(overrides || {})
  };
}

/**
 * 优先级：dragging > error > waiting > acting > thinking > speaking > idle > sleeping。
 *
 * error 高于 waiting，但调用方 MUST NOT 在 error 时清除 proposalPending；
 * 这样 error 解除后 waiting 会自动恢复。
 */
export function resolveLifecycleState(conditions) {
  const c = conditions || {};
  if (c.dragging) return 'dragging';
  if (c.errorLatched) return 'error';
  if (c.proposalPending) return 'waiting';
  if (c.turnInFlight && c.toolActive) return 'acting';
  if (c.turnInFlight) return 'thinking';
  if (c.bubbleVisible) return 'speaking';
  if (c.sleeping) return 'sleeping';
  return 'idle';
}

/** 角色的无控制台可观测文案（写到 title / avatar aria-label）。 */
export function lifecycleTitle(state) {
  return '伴读 · ' + (STATE_LABELS[state] || STATE_LABELS.idle);
}

/** 状态名是否合法；用于调用方防御拼写漂移。 */
export function isLifecycleState(state) {
  return LIFECYCLE_STATES.includes(state);
}
