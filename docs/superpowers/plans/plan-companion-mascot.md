# 内置陪伴角色（Companion Mascot）「Eule」🦉 — 可自定义版

> **本计划已核对当前 master（v3.5.1）源码**，下列关键行号均为实测：`saveVocab` reader.js:423、
> `saveGrammar` reader.js:441、`submitCardReview` cards.js:243（当前丢弃响应）、`finishQuiz` cards.js:691
> （德语格言段 :708-714）、`ShadowPlayer.init()` main.js:645、window 导出 main.js:542、
> mobile-bottom-nav index.html:791-808、`<script>` index.html:810、移动端断点 style.css:4848（768px）、
> `playGermanAudio` player.js:6、`#quiz-confetti`/`#milestone-toast` index.html:726/744（死占位）。
> 执行时若再漂移，以本文档为准核对。

## Context

用户想给 DeLector 加一个"陪伴、鼓励"效果的功能，像 Duolingo 等陪伴型软件。经评估与技术栈核对：

- **形态定案**：内置到 App 界面的陪伴角色（三端通用：桌面浏览器 / Windows 便携版 / Android WebView）。
  **OS 级桌面悬浮浮窗在技术栈上不可行**——DeLector 是浏览器内 Web App，无原生窗口层，需 Electron/Tauri/原生程序，判为另一工程。
- **发声定案**：角色用德语 TTS 开口（复用现有三层 TTS）。
- **内容定案**：本地德语模板库 + 事件触发，本阶段不接 DeepSeek。
- **自定义定案**（用户多选）：**预置多角色切换 + 命名 + 自定义主题色 + 模块化预留 SVG 上传**；
  自定义操作放在**角色自身弹出的小面板**里。

**可行性依据**（探索 + 直接核实）：
- 前端 vanilla JS ES Modules，`index.html` body 是平铺兄弟节点，常驻浮层都是 `position:fixed` 子节点；z-index **60–79 空档位**可用（高于 `#shadow-player` z50，低于抽屉/cloze z90）。
- 现成钩子：`submitCardReview`（cards.js:243，返回完整 SM-2 数据）、`submitClozeExercise`（cloze.js:122，`accuracy_pct`）、`finishQuiz`（cards.js:691，已有德语格言段）、死占位 `#quiz-confetti`/`#milestone-toast`（index.html:726/744）、`showUndoToast` 气泡样式（cards.js:404）。
- `playGermanAudio(text)`（player.js:6）一次调用自动走 Android 原生 → Edge TTS → Web Speech 三层回退，顺应用户 tts_voice/tts_rate；player.js 只 import core.js，companion 引它无循环。
- Android WebView 用 `window.AndroidNativeTTS` 检测（v3.5.1 原生 TTS 桥已真机验证）。
- 数据缺口：阅读未记 streak（`log-read` 孤儿端点）；无首次/回归访问信号（需新增 localStorage 访问戳）。

## 已确认决策
- 内置陪伴角色；德语 TTS 发声；本地模板库（无 AI）。
- **可自定义**：预置多角色（内联 SVG，零图片文件）、命名、主题色、模块化预留 SVG 上传（本阶段先做注册表 + 预置，上传 UI 为阶段 2）。
- 自定义入口：**角色自身弹出小面板**（自包含，不动设置弹窗/后端）。

---

## 实现方案

### 1. 角色模型：模块化角色注册表 + 内联 SVG（非单一 CSS 猫头鹰）

`companion.js` 内一个角色注册表，每个角色 = 名称 + 默认主题色 + 内联 SVG 模板：

```js
const CHARACTERS = {
  owl:   { name: 'Eule',   primary: '#6b4f8f', accent: '#e8953a', svg: '<svg ...>...</svg>' },
  cat:   { name: 'Katze',  primary: '#4f8f6b', accent: '#f0e6d0', svg: '...' },
  fox:   { name: 'Fuchs',  primary: '#d9663f', accent: '#f2e6c9', svg: '...' },
  robot: { name: 'Roboter',primary: '#4a6fa5', accent: '#9bd1f0', svg: '...' }
};
Companion.registerCharacter(id, def)  // 模块化接缝：阶段 2 的上传 SVG 走这里
```

- 每个 SVG 用**共享类名**标注可动画部件：`.char-eye`（眨眼 scaleY）、`.char-body`（跳跃/垂头 transform）、`.char-ear`（可选）。动画按类名作用，跨角色通用。
- **主题色**：SVG 填充用 CSS 变量 `var(--c-primary)` / `var(--c-accent)`，由 JS 从用户主题色设置内联到 `#companion-char` 上 → 任一预置角色一键换色。
- 自定义 SVG（阶段 2）：无这些类名 → 只保留整角色 idle/跳跃，眨眼/垂头降级跳过。文档写明。
- 选择 `localStorage.delector_companion_char`；换角色 = 重渲染 SVG 节点，动画/事件逻辑不变。

### 2. DOM + CSS

角色容器 + 气泡 + **自定义面板**（都在 `#companion` 内，插在 `.mobile-bottom-nav` 之后、`<script>`（index.html:810）之前）：

```html
<div id="companion" class="companion" role="status" aria-live="polite">
  <div id="companion-bubble" class="companion-bubble hidden">
    <div class="companion-bubble-de" id="companion-de"></div>
    <div class="companion-bubble-zh" id="companion-zh"></div>
  </div>
  <div id="companion-char" class="companion-char"></div>   <!-- JS 注入所选角色 SVG -->
  <button id="companion-avatar" class="companion-avatar" aria-label="陪伴角色" onclick="window.Companion.onClick()"></button>
  <div id="companion-panel" class="companion-panel hidden">
    <div class="panel-row" id="panel-characters"></div>     <!-- 角色网格 + 自定义槽 -->
    <div class="panel-row"><input id="panel-name" type="text" maxlength="12" placeholder="起个名字…"></div>
    <div class="panel-row" id="panel-colors"></div>         <!-- 色板 + <input type=color> -->
    <div class="panel-row">
      <button id="panel-say" onclick="window.Companion.onSay()">💬 说句话</button>
      <button id="panel-sound" onclick="window.Companion.toggleSound()">🔊</button>
      <button id="panel-hide" onclick="window.Companion.toggleEnabled()">✕</button>
    </div>
    <!-- 阶段 2：<button id="panel-upload">上传 SVG</button> + <input type=file accept=".svg"> -->
  </div>
</div>
```

- 定位 `#companion { position:fixed; right:16px; bottom:16px; z-index:70 }`。
- **移动端**：`@media (max-width: 768px)`（实测断点 **768px**，style.css:4848）→ `bottom: calc(56px + env(safe-area-inset-bottom,0) + 10px); transform: scale(0.85)`。
- **抽屉打开**（`body.drawer-open`）：角色左移 `right: calc(var(--drawer-width) + 16px)`，不隐藏。
- **弹层之上**：quiz(z999)/cloze(z90) 打开时 JS 给 `#companion` 加 `.ontop`（`z-index:1000 !important`）。
- 气泡样式：纸色底 + 墨色粗边框 + 硬阴影 + `::after` 尾巴；德语 `var(--serif-heading)`、中文小号副行；`pointer-events:none`。
- **面板**：`#companion-panel` 绝对定位于角色上方，同样纸/墨风格，`pointer-events:auto`；点角色头像 toggle。
- 禁用后（`delector_companion_enabled='off'`）`#companion` 塌缩成单个小 `🦉` ghost pill，点击恢复。

### 3. 动画（复用屋子缓动 `cubic-bezier(0.16,1,0.3,1)`）
| keyframe | 效果 | 触发 |
|---|---|---|
| `charBlink` | `.char-eye` scaleY→0.1 每 ~4s | 常开 |
| `companionIdle` | translateY ±3px 呼吸 | 常开 |
| `companionJump` | 3 次弹跳 | 开心（制卡/复习 Good/测验完成） |
| `companionWiggle` | 旋转微晃 | 鼓励（streak/复习 Hard） |
| `companionDroop` | 下沉 + 眼睛收窄 | 低落（复习 Again，可选） |
| `bubblePop` | scale 0.85→1 气泡入场 | say() |

情绪用 `#companion-char` 上 `.is-happy/.is-wiggle/.is-sad` 类，`animationend` 后移除。

### 4. 事件接线：中央模块 + 显式调用（不用 api() 包装）
- **新建 `static/js/companion.js`**：角色注册表 + SVG 模板、面板渲染、短语库、say/celebrate、情绪动画、冷却、localStorage 设置、日常问候 + streak 检查、`playGermanAudio` 发声。导出 `Companion`（main.js `Object.assign(window, {Companion})`）。ES module 单例，无双重 import。
- 选显式调用而非包装 `api()`：包装器无法区分"制卡"vs"复习"（同是 POST /api/cards/...），且 `finishQuiz` 是纯 DOM、数据在响应里。
- **Companion API**：`init()`、`onClick()`（toggle 面板）、`onSay()`（随机 idle 短语并说）、`say(entry)`、`celebrate(key,data)`、`toggleSound()`、`toggleEnabled()`、`registerCharacter(id,def)`（模块化接缝）。
- **钩子点**（file:位置 → 调用）：
  1. 日常问候 — main.js DOMContentLoaded:639-646 旁 `Companion.init()`；`localStorage.delector_visit_date` ≠ 今天 → `celebrate('greeting')` 盖戳。
  2. 生词卡 — reader.js `saveVocab()` 成功后 → `celebrate('card_vocab')`。
  3. 语法卡 — reader.js `saveGrammar()` 成功后 → `celebrate('card_grammar')`。
  4. SM-2 复习 — cards.js `submitCardReview()`（现在丢弃响应）→ 捕获响应，`grade>=3 ? 'review_good' : 'review_hard'`。
  5. 完形 ≥80% — cloze.js `accuracy_pct>=80` 分支 → `celebrate('cloze_great',{pct})`。
  6. 测验完成 — cards.js `finishQuiz()` 格言段后 → `celebrate('quiz_done',{pct})`。
  7. streak 里程碑 — folio.js `loadProgress()` 后：`streak>=3` 且 > 已庆祝值 → `celebrate('streak',{n})`，存 `delector_streak_celebrated`。（streak 因阅读未记而可能为 0——已知怪癖，本阶段不修）
  8. （可选，易噪音）导入文章成功 → `celebrate('new_article')`，默认跳过。

### 5. 短语库（companion.js 内）
```js
const PHRASES = {
  greeting: [{de:"Hallo! Schön, dich zu sehen!", zh:"你好！很高兴见到你！"}],
  card_vocab: [{de:"Super! Ein neues Wort gelernt!", zh:"太棒了！又学到一个新单词！"}],
  card_grammar:[...], review_good:[...], review_hard:[...],
  cloze_great:[{de:"Stark! {pct}% richtig!", zh:"真厉害！正确率 {pct}%！"}],
  quiz_done:[...], streak:[{de:"Schon {n} Tage in Folge!", zh:"已经连续学习 {n} 天！"}],
  idle:[{de:"Lass uns etwas lesen!", zh:"我们一起读点什么吧！"}]
};
```
- 德语目标 A1–B1：短句、现在时、高频词、无从句（如 "Weiter so!"）。
- `Math.random()` 随机 + "连抽不重复"守卫；`{pct}`/`{n}` 替换；中文副行用 `textContent`（防注入）。
- **命名前缀**：若用户起了名，气泡德语行前加 `<名字>: `（如 "Eule: Weiter so!"）。

### 6. 发声 + 冷却 + 开关
- 用 `playGermanAudio(entry.de, 0.88)`（player.js:6 导入，无循环）。
- **冷却** `COMPANION_COOLDOWN_MS = 8000` + `lastSpeechAt`；气泡**总是立刻显示**，只有满足才发声：声音开、冷却过、`!ShadowPlayer.isPlaying`（Android 原生桥 QUEUE_FLUSH 会掐断影子跟读）。
- **开关/设置**（面板内）：`delector_companion_sound`、`delector_companion_enabled`、`delector_companion_char`、`delector_companion_name`、`delector_companion_color`——全在 localStorage，零后端。

### 7. PWA / Service Worker
- 无需 precache（network-first 运行时缓存，companion.js 首次请求即入缓存）；`STATIC_ASSETS` 补 `/js/companion.js` 备档。
- **版本 bump 3.5.1 → 3.6.0**：`sw.js` `CACHE_NAME='delector-static-v3.6.0'`；index.html 的 `style.css?v=3.6.0`、`js/main.js?v=3.6.0`。

### 8. Android
- **零 Android 侧改动**：原生离线 TTS 已桥接，companion 走同一路径，WebView 离线可发声。
- QUEUE_FLUSH 隐患：`!ShadowPlayer.isPlaying` + 8s 冷却缓解；短语保持一句话。
- `navigator.vibrate` 可选：onClick 加 15ms 微震动反馈。

---

## 文件清单

| 操作 | 路径 | 说明 |
|---|---|---|
| 新建 | `static/js/companion.js` | 角色注册表 + SVG 模板、面板渲染、短语库、say/celebrate、情绪动画、冷却、localStorage 设置、问候 + streak、playGermanAudio、registerCharacter 接缝 |
| 修改 | `static/index.html` | 插 `#companion`（角色 + 气泡 + 面板）节点（mobile-bottom-nav 后、script 前）；`?v=3.6.0` |
| 修改 | `static/style.css` | `/* v3.6 Companion */` 段：定位/z-70/移动端/抽屉/弹层/气泡/角色 SVG 尺寸/面板/色板/keyframes ×6 |
| 修改 | `static/js/main.js` | import Companion、window 导出（542 处）、DOMContentLoaded 调 `Companion.init()`（645 旁） |
| 修改 | `static/js/reader.js` | saveVocab/saveGrammar 后 celebrate |
| 修改 | `static/js/cards.js` | submitCardReview 捕获响应分支；finishQuiz 后 celebrate |
| 修改 | `static/js/cloze.js` | accuracy_pct≥80 分支 celebrate |
| 修改 | `static/js/folio.js` | loadProgress streak 里程碑 |
| 修改 | `static/sw.js` | CACHE_NAME v3.6.0；STATIC_ASSETS 补 companion.js |

**执行顺序**：companion.js（注册表 + 面板 + 短语 + 动画 + 发声）→ 5 个 JS 接线 → CSS → index.html 节点 + `?v=` → sw.js → 手动验证。

---

## 验证方式
- **桌面浏览器**：`python server.py`，开 http://127.0.0.1:8000，控制台零报错。逐项：
  - 右下角 idle 呼吸可见；点角色 → 弹出面板。
  - **换角色**：面板切猫/狐狸/机器人 → 即时换 SVG、动画仍工作；刷新后保留（localStorage）。
  - **命名**：输入名字 → 气泡德语行出现 `<名字>: ` 前缀。
  - **主题色**：选色 → 角色配色即时变、刷新保留。
  - 问候：清 `delector_visit_date` 后刷新 → greeting 气泡。
  - 制卡/复习/完形/测验/streak：逐项按 §4 钩子触发对应反应；完形 ≥80% 反应**在弹层之上**（测 `.ontop`）。
  - 开关：🔊→🔇 气泡仍在、无声音；✕ → 塌缩 ghost pill；点击恢复。
  - 冷却：8s 内连触两事件 → 第二个只显气泡不发声。
  - PWA：刷新后 Network 显示缓存 `delector-static-v3.6.0`，旧缓存被清。
- **Windows 便携版**：重打包后在 `dist/.../_internal/static/` 复核关键项（离线）。
- **Android WebView**：跑 Chaquopy 版，确认原生离线 TTS 发声；影子跟读播放中触发复习反应 → 不掐断跟读；窄屏气泡/面板不溢出。
- **后端/测试**：本阶段**纯前端**，无新路由、无新 pytest；跑现有 64 个测试确认无回归。

## 范围守卫
**本阶段做**：预置 4 角色（内联 SVG）+ 命名 + 主题色 + 面板自定义入口 + 事件反应 + 德语发声 + 本地模板库。
**本阶段不做（阶段 2）**：
- **SVG 上传 UI**（文件选择/解析/存储）——只预留 `registerCharacter` 模块化接缝，上传入口留空位。
- AI/DeepSeek 个性化鼓励
- 宠物成长/升级/XP/喂食
- 设置弹窗内集成（自定义走角色自身面板）
- OS 级桌面悬浮宠物
- 新后端路由、streak 数据缺口修复
- 图片/精灵资产或构建步骤
