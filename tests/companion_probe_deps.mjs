/**
 * companion_probe_deps.mjs —— 桌宠探针共享依赖表
 *
 * `static/js/companion.js` 的直连 import 只在这里登记一次：
 *   - `tests/test_companion_bubble_resume_probe.mjs`
 *   - `tests/test_companion_context_probe.mjs`
 * 两个 harness 都从这里取源码，新增一个 import 时只改这一处，不用两边补桩。
 *
 * 策略：
 *   - `./player.js` / `./cd-state.js`（默认）用最小桩：它们在真实环境里会碰
 *     localStorage / 浏览器全局，探针只关心 companion 自身逻辑；
 *   - `./companion-obstacles.js` / `./companion-lifecycle.js` 读**真源码**：
 *     两者都是 L1 纯模块，可直接在 vm 里跑；
 *   - `realCdState: true` 时 `./cd-state.js` 也读真源码（上下文探针需要真容器）。
 *
 * 未登记的 specifier 会在 link 阶段抛「探针未提供依赖桩: ./xxx.js」——
 * 新增 import 时按这条报错回来这里补一行即可。
 */
import fs from "node:fs";
import path from "node:path";

export const PLAYER_STUB_SRC =
  "export const ShadowPlayer = { isPlaying: false };\n" +
  "export function playGermanAudio() {}\n";

export const CD_STATE_STUB_SRC =
  "export const cardState = {};\n" +
  "export function selectSegmentLists() { return {}; }\n" +
  "export function buildDeckFromLists() { return []; }\n";

/**
 * @param {string} root 仓库根目录
 * @param {{ realCdState?: boolean }} [options]
 * @returns {Record<string, string>} specifier → 模块源码
 */
export function companionDependencySources(root, options = {}) {
  const read = (rel) => fs.readFileSync(path.join(root, rel), "utf8");
  return {
    "./player.js": PLAYER_STUB_SRC,
    "./cd-state.js": options.realCdState ? read("static/js/cd-state.js") : CD_STATE_STUB_SRC,
    "./companion-obstacles.js": read("static/js/companion-obstacles.js"),
    "./companion-lifecycle.js": read("static/js/companion-lifecycle.js")
  };
}
