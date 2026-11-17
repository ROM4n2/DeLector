/**
 * update_flow_probe.mjs —— 应用内更新面板的纯展示逻辑行为探针（ADR-0034 / M2）。
 *
 * 被测对象是 `static/js/update-flow.js` 的**真实源码**：用 data URL 作为 ES 模块导入，
 * 探针里不重抄一份实现。只做纯函数断言（无 DOM、无网络、无计时器）。
 *
 * 用法：node tools/update_flow_probe.mjs --json
 * 输出：`{ ok: true, <场景名>: "<一句人话>" }`；有失败则写 stderr 并 exit 1。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SOURCE = path.join(ROOT, "static", "js", "update-flow.js");

const src = fs.readFileSync(SOURCE, "utf8");
const moduleUrl = "data:text/javascript;base64," + Buffer.from(src, "utf8").toString("base64");
const flow = await import(moduleUrl);

const problems = [];
const check = (name, condition, detail) => {
  if (!condition) problems.push(`${name} :: ${detail}`);
};

/* 1. 百分比边界 */
const percentCases = [
  [0, 100, 0],
  [50, 100, 50],
  [100, 100, 100],
  [150, 100, 100],
  [0, 0, 0],
  [Number.NaN, 100, 0],
];
for (const [done, total, expected] of percentCases) {
  check(
    "percent_edges",
    flow.updateProgressPercent(done, total) === expected,
    `(${done}/${total}) => ${flow.updateProgressPercent(done, total)} != ${expected}`,
  );
}

/* 2. 下载中：文案带百分比 + 可取消 */
const downloading = flow.describeUpdateSnapshot({
  state: "downloading",
  downloaded_bytes: 25,
  total_bytes: 100,
});
check("download_view", downloading.text === "下载中 25%" && downloading.showCancel === true, JSON.stringify(downloading));

/* 3. 校验中 */
const verifying = flow.describeUpdateSnapshot({ state: "verifying" });
check("verifying_view", verifying.text.indexOf("校验") !== -1 && verifying.showCancel === true, JSON.stringify(verifying));

/* 4. 就绪：不可取消，交给自动安装 */
const ready = flow.describeUpdateSnapshot({ state: "ready" });
check("ready_view", ready.text.indexOf("安装") !== -1 && ready.showCancel === false, JSON.stringify(ready));

/* 5. 失败：人话 + Release 退路 */
const failed = flow.describeUpdateSnapshot({ state: "failed", error_reason: "no_space" });
check(
  "failed_humanized",
  failed.text.indexOf("空间不足") !== -1 && failed.showRelease === true && failed.terminal === true,
  JSON.stringify(failed),
);

/* 6. 未知 reason：兜底，绝不回显原始串（含 HTTP 状态码） */
const unknown = flow.describeUpdateSnapshot({ state: "failed", error_reason: "HTTP 500 boom" });
check(
  "unknown_reason_fallback",
  unknown.text.indexOf("HTTP") === -1 && unknown.text === "更新失败，请稍后重试",
  JSON.stringify(unknown),
);

/* 7. 空闲：无文案、无动作 */
const idle = flow.describeUpdateSnapshot({ state: "idle" });
check("idle_view", idle.text === "" && idle.showCancel === false && idle.showRelease === false, JSON.stringify(idle));

if (problems.length) {
  console.error("update_flow_probe FAIL:\n" + problems.join("\n"));
  process.exit(1);
}

process.stdout.write(
  JSON.stringify({
    ok: true,
    percent_edges: "0/50/100/越界/零总量/NaN 六组边界一致",
    download_view: "下载中带百分比且可取消",
    verifying_view: "校验中文案且可取消",
    ready_view: "就绪不可取消",
    failed_humanized: "失败给空间不足人话并保留 Release 退路",
    unknown_reason_fallback: "未知 reason 走兜底且不回显原始串",
    idle_view: "空闲零动作",
  }),
);
