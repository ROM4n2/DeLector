# 前端动效验证方法（CDP 三层采样）

> 适用：验证 `static/` 的入场、错峰、计数、按压、焦点环、`prefers-reduced-motion` 降级。
> 结论以**运行时**为准，不靠读 CSS 猜。所有「已验证」必须附采样层与等待时长。

---

## 0. 为什么需要三层

单看 CSSOM 只能证明「规则写了」；单看截图只能证明「某一瞬间长这样」。动效有三类失败：

| 失败 | 只看 CSS 会漏掉 | 对应采样层 |
|---|---|---|
| 规则被覆盖 / 选择器没命中 | 是 | 第 1 层：CSSOM + computed style |
| 动画没启动 / 重播 / 延迟不对 | 是 | 第 2 层：`document.getAnimations()` |
| reduce 下仍在动 / 落不到终态 | 是 | 第 3 层：`Emulation.setEmulatedMedia` |

三层都过，才算验证完成。

---

## 1. 启动可调试的无头浏览器

```powershell
# 任选一个 Chromium 内核
$chrome = "$env:LOCALAPPDATA\ms-playwright\chromium-1234\chrome-win64\chrome.exe"
# 或 Edge：$chrome = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

& $chrome --headless=new --remote-debugging-port=9222 --disable-gpu `
  --user-data-dir="$env:TEMP\dl-motion-profile" `
  "http://localhost:8000"
```

确认目标页：

```powershell
(Invoke-RestMethod http://127.0.0.1:9222/json/list) |
  Where-Object { $_.type -eq "page" } |
  Select-Object id, url, webSocketDebuggerUrl
```

> **坑**：不要连 `/json/version` 返回的 **browser** WebSocket。它只能发浏览器级命令，`Runtime.evaluate` 会得到 `undefined`。必须连 `/json/list` 里 `type=page` 的 `webSocketDebuggerUrl`。

连接与发命令的最小骨架（Node ≥22，自带全局 `WebSocket`）：

```js
// probe.mjs
const targets = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = targets.find((t) => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));

let seq = 0;
const pending = new Map();
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
  }
};
const send = (method, params = {}) =>
  new Promise((resolve) => {
    const id = ++seq;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });

const evalJS = async (expression) => {
  const r = await send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails));
  return r.result?.result?.value;
};
```

---

## 2. 第 1 层：CSSOM + computed style

先固定视口，再读终端态：

```js
await send("Emulation.setDeviceMetricsOverride", {
  width: 1440, height: 900, deviceScaleFactor: 1, mobile: false,
});

const out = await evalJS(`(() => {
  const el = document.querySelector(".btn");
  const cs = getComputedStyle(el);
  return {
    outline: cs.outline,
    outlineOffset: cs.outlineOffset,
    transition: cs.transition,
    transitionDuration: cs.transitionDuration,
    animation: cs.animationName,
  };
})()`);
```

要证明「规则确实命中」，除 computed style 外再查匹配规则：

```js
const rules = await evalJS(`(() => {
  const el = document.querySelector(".btn");
  const hit = [];
  for (const sheet of document.styleSheets) {
    let list;
    try { list = sheet.cssRules; } catch { continue; } // 跨域样式表读不到
    for (const r of list) {
      if (!r.selectorText) continue;
      try { if (el.matches(r.selectorText)) hit.push(r.cssText); } catch {}
    }
  }
  return hit;
})()`);
```

> 跨域样式表 `cssRules` 会抛异常；本仓自托管 CSS 不受影响。外部参考页要标 UNVERIFIED。

### 2.1 必须等过渡结束

**坑：`transition: all` 让探针读到过渡中间值。**

`.btn` 带有 `transition: all var(--dur-fast) ease`，`outline` 也在过渡。T9 焦点环实测：

| 采样时机 | 读到的值 | 误判 |
|---|---|---|
| 聚焦后 40ms | `outline: rgb(10,9,7) solid 2px; offset 1px` | 以为是 UA 默认环，规则没生效 |
| 聚焦后 ≥360ms | `outline: 2px solid rgb(21,20,15); offset 2px` | 正确终值 |

规则：**读终态前等待 `max(transition-duration)`，本仓至少等 `--dur-mid`（360ms）**。更稳的做法是等 `transitionend`，或先读 `getAnimations()` 确认没有运行中的 `CSSTransition`。

---

## 3. 第 2 层：运行时 `document.getAnimations()`

这一层回答：动画有没有真的跑、跑的是谁、延迟多久、跑几轮。

```js
const running = await evalJS(`(() => {
  return document.getAnimations().map((a) => {
    const t = a.effect?.getTiming?.() || {};
    return {
      kind: a.constructor.name,                 // CSSAnimation / CSSTransition
      name: a.animationName || a.transitionProperty,
      playState: a.playState,
      iterations: t.iterations,
      duration: t.duration,
      delay: t.delay,
      target: a.effect?.target?.className || a.effect?.target?.id || "",
    };
  });
})()`);
```

判据：

- 入场：`CSSAnimation` 的 `name === "dl-fade-up"`，`iterations === 1`。
- 错峰：每个子项的 `delay` 应为 `min(i, cap-1) * 40ms`。
- 循环白名单：`iterations === Infinity` 只允许 7 处（光标 / 眨眼 / 待机 ×2 / marquee ×2 / 音频忙碌）。
- 按压：`CSSTransition` 的 `transitionProperty === "transform"`、`duration === "0.1s"`。
- 过渡结束后 `document.getAnimations()` 应为空或只剩白名单循环。

### 3.1 隐藏视图不跑动画

`.view` 靠 `display: none/block` 切换；隐藏视图里的元素不会运行动画或过渡。采样前先切到目标视图：

```js
await evalJS(`show('progress')`); // main.js 暴露的全局切换函数
```

否则会得到「0 个动画」的假阴性。

---

## 4. 第 3 层：`prefers-reduced-motion` 模拟

```js
await send("Emulation.setEmulatedMedia", {
  features: [{ name: "prefers-reduced-motion", value: "reduce" }],
});
await evalJS(`location.reload()`);
```

等页面就绪后重跑第 2 层，判据：

1. `getAnimations()` 里**不存在** `name === "dl-fade-up"` 的运行实例。
2. 入场元素直接可见（`opacity: 1`），不是停在 `from` 帧。
3. 按压后 `transform === "none"`。
4. 7 处白名单循环全部 `animation-name: none` 或时长为 `0.01ms`。

验证完恢复：

```js
await send("Emulation.setEmulatedMedia", { features: [] });
```

---

## 5. 触发式采样

`getComputedStyle` 只给当前状态。hover / active 必须**先触发再采样**。

### 5.1 强制伪类（不需要真实鼠标）

```js
await send("DOM.enable");
await send("CSS.enable");
const { result } = await send("DOM.getDocument", { depth: -1 });
const { result: node } = await send("DOM.querySelector", {
  nodeId: result.root.nodeId,
  selector: ".stat-badge",
});
await send("CSS.forcePseudoState", {
  nodeId: node.nodeId,
  forcedPseudoClasses: ["hover"],
});
// 等 ≥360ms 再读 computed style
```

`forcePseudoState` 会让过渡真的跑起来，所以同样要等过渡结束再读终值。

### 5.2 `:focus-visible` 必须用真实键盘

`:focus-visible` 取决于输入模态；`element.focus()` 与 `forcePseudoState` 都可能不触发它。用 CDP 发真实 Tab：

```js
await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
```

然后读 `document.activeElement` 的 `outline`，等待 ≥360ms。

### 5.3 触屏 / 粗指针

`@media (hover: hover) and (pointer: fine)` 的 hover 规则在无头桌面默认生效。要验证触屏不粘住：

```js
await send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
await send("Emulation.setDeviceMetricsOverride", {
  width: 390, height: 844, deviceScaleFactor: 3, mobile: true,
});
```

再 `location.reload()`，强制 `:hover` 后断言目标样式不变，`:active` 反馈仍在。

---

## 6. 错峰（stagger）还原

`enterOnce()` 的行为是「挂类 → 播放 → 自动摘类」，所以采样窗口很窄：

- 挂类后立即采样：`class="dl-enter"`、`style="--stagger-index: i"`、`getAnimations()` 有 `dl-fade-up`。
- 430ms 后采样（`180 + 40×5 + 50`）：类与序号都被移除，`getAnimations()` 不再有 `dl-fade-up`。

复现方式：在触发前注入一个 `MutationObserver`，记录类变化，而不是事后猜：

```js
await evalJS(`(() => {
  window.__motionLog = [];
  const root = document.getElementById("exam-module-grid");
  new MutationObserver((list) => {
    for (const m of list) {
      window.__motionLog.push({
        t: Math.round(performance.now()),
        target: m.target.className,
        added: [...m.addedNodes].length,
        attr: m.attributeName,
      });
    }
  }).observe(root, { subtree: true, attributes: true, childList: true });
})()`);

// 触发
await evalJS(`show('exam')`);

// 采样
await evalJS(`window.__motionLog`);
```

期望：每个子项 `--stagger-index` 依次为 0..5，第 7 项仍为 5（cap 6）；430ms 后类被摘掉。

> 若在 430ms 后才采样，会看到「类不存在、动画为 0」，这不是失败，是采样太晚。

---

## 7. 两条必须记住的实战坑

### 7.1 `transition: all` 会污染探针

本仓大量规则使用 `transition: all var(--dur-fast)`（`style.css` 60+ 处）。任何属性变更（包括 `outline`、`box-shadow`）都会过渡，探针在 0–359ms 之间读到的是中间值。

**规则**：读终态前等 `≥360ms`（`--dur-mid`），或用 `getAnimations()` 等到 `playState === "finished"`。不要用 0ms / 16ms / 40ms 的采样下结论。

### 7.2 `index.html` 只加载 `style.css`，token 必须双份镜像

- 主应用：`static/index.html` → `static/style.css`
- Workbench：加载 `static/css/tokens.css`
- `static/index.html` **不加载** `tokens.css`

因此任何新 token（含 5 个 motion token）必须同时写在：

1. `static/style.css` 的 `:root`
2. `static/css/tokens.css` 的 `:root`

只写 `tokens.css`，主应用的 `.dl-enter` 会拿不到时长，`getAnimations()` 里 `duration: "0s"`，动画静默失效。

静态核对：

```powershell
Select-String -Path static/style.css, static/css/tokens.css -Pattern "--motion-enter:|--motion-press:|--motion-count:|--motion-stagger-step:|--motion-enter-shift:"
# 期望：5 个 token × 2 个文件 = 10 行
```

---

## 8. 本仓验收清单（逐条可复现）

| # | 验证项 | 采样层 | 判据 |
|---|---|---|---|
| 1 | 5 个 motion token 双份镜像 | 静态 | 两文件各 5 行，共 10 行 |
| 2 | 入场只播一次 | 第 2 层 | 首次触发有 `dl-fade-up`；切回视图后为 0 |
| 3 | 错峰 40ms / cap 6 | 第 2 层 + MutationObserver | 第 7 项 delay 同第 6 项 |
| 4 | 计数 520ms 只播一次 | 第 2/3 层 | 首次有计时；`dataset.countPlayed` 后不再播 |
| 5 | 焦点环 2px `--ink` / offset 2px | 第 1 层 | 真实 Tab 后 **等 360ms** 读终值 |
| 6 | reduce 下无入场、无按压缩放 | 第 3 层 | `dl-fade-up` 实例 0；`transform: none` |
| 7 | 循环只剩 7 处白名单 | 静态 + 第 2 层 | `grep -rn "infinite" static/` = 7 行 |
| 8 | 阅读面零位移 | 第 1/2 层 | `.tok` / `.a1-option-label` 强制 `:active` 后 `transform: none` |

静态闸门先跑：

```powershell
grep -rn "infinite" static/        # 7 行白名单
python tools/build_index_html.py
python tools/check_index_html_sync.py
```

---

## 9. 清理

```powershell
Get-Process chrome, msedge -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item -Recurse -Force "$env:TEMP\dl-motion-profile"
```
