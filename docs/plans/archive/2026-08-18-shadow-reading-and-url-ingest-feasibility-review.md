# DeLector Phase 4 计划可行性评估报告

> **评审对象**：[2026-08-18-shadow-reading-and-url-ingest.md](./2026-08-18-shadow-reading-and-url-ingest.md)（Phase 4：影子跟读播放器、URL 一键抓取、备份同步、跨平台启动器）
> **评审日期**：2026-08-18
> **方法**：逐任务对照真实代码逐条核对（`server.py` / `test_server.py` / `static/index.html` / `static/app.js` / `static/style.css` / `requirements.txt` / `docs/design-system.md`），7 个独立任务分析器并行产出发现 → 逐条对抗性验证（尝试证伪）→ 完整性批判代理查跨任务漏洞。确认 51 条发现 + 10 条跨任务发现，5 条被验证器驳回。
> **结论**：**方向正确，但当前稿不能照单实施。** 存在 5 个阻断级缺陷（含 2 个安全漏洞）、十几个直接出 bug 的主要缺陷，且计划内部接口命名自相矛盾、多项承诺未落地。

---

## 一、总体评价

技术栈选择（FastAPI + 静态前端 + Web Speech API + 复用现有 `process_german_text`/`ingest_article` 流水线）与现有代码高度契合，ShadowPlayer 的「模式机 + 停顿计时器」思路成立。但计划存在以下等级的问题：

| 等级 | 数量 | 含义 |
| :--- | :--- | :--- |
| 🔴 阻断 | 5 | 功能直接坏掉或安全漏洞，不改不开工 |
| 🟠 主要 | ~14 | 明确 bug、数据丢失、或达不到承诺 |
| 🟡 次要 | ~10 | 打磨项、鲁棒性 |
| ⚪ 被驳斥但值得保留 | 2 | 验证器误驳，内核仍成立 |

---

## 二、阻断级缺陷（必须先改）

### 🔴 1. SSRF：URL 抓取可被 LAN 内任何设备用来打内网 [T1]

计划只校验 `url.startswith("http://")`，然后 `httpx.AsyncClient(follow_redirects=True)` 服务端直取（计划 L99/L107）。配合 T6 把服务绑到 `0.0.0.0`，局域网内任意客户端都能让服务器去抓 `127.0.0.1:3306`、Docker 容器、`169.254.169.254` 云元数据等内部地址。响应正文会被整段存入库，错误信息还会泄露目标 HTTP 状态码。

**修复**：解析 host 后，在**每次跳转后**用 `ipaddress` 校验目标 IP，拒绝私有/环回/链路本地/ULA（`127/8`、`10/8`、`172.16/12`、`192.168/16`、`169.254.169.254`、`::1`、`fd00::/8`），只允许 http/https scheme。

### 🔴 2. 无鉴权备份导出/还原 + 绑 0.0.0.0 → 全库可读、可被远程覆盖 [T5+T6]

`GET /api/backup/export` 任何人可下载整库（文章 + 生词卡 + 语法卡），`POST /api/backup/restore` 用 `INSERT OR REPLACE` 可覆盖任意行（计划 L687-722）。绑定 `0.0.0.0` 后，这就是 LAN 上的裸奔数据库。

**修复**：备份接口加简单令牌（如 `.env` 中的 `BACKUP_TOKEN`，restore 要求 header）；或默认只绑 `127.0.0.1`，由用户显式开 LAN。现有 `.env` 已有 `DEEPSEEK_API_KEY` 先例，加一个不破坏现有约束。

### 🔴 3. export 端点会直接 NameError：`datetime` 未导入 [T5]

[server.py:1-13](../../server.py#L1-L13) 的 import 里没有 `datetime`，计划的 `datetime.now().isoformat()` 一调用就崩。同类问题：T1 的 `Tuple[str, str]` 注解——[server.py:6](../../server.py#L6) 只导入了 `Optional, List, Dict, Any`。Python 3.11 在 def 时立即求值注解，贴进计划代码后**整个模块 import 失败，所有测试全挂**。

**修复**：`from datetime import datetime`；`Tuple` 补进 typing import（或加 `from __future__ import annotations`）。

### 🔴 4. `cancel()/speak()` 竞态：播放中点「下一句/重播/调速」会直接停播 [T3]

计划的 `speakCurrentSentence` 每句都先 `speechSynthesis.cancel()` 再 `speak()`，且 `utt.onerror = () => this.pause()`（计划 L361/L395）。Chrome 里 cancel 一个正在朗读的 utterance 会触发 `onerror`（`error: 'interrupted'/'canceled'`）→ 走 `pause()` → 刚 seek 过去的句子被立刻掐断、播放停掉。**最常用的「边听边跳句」交互直接坏**。

**修复**：

```js
utt.onerror = (e) => { if (e.error !== 'interrupted' && e.error !== 'canceled') this.pause(); };
```

并避免无谓的 `cancel()`（仅在确有旧 utterance 在播时才 cancel）。

### 🔴 5. `position: fixed` 失效：播放器会锚在文章末尾，不是视口底部 [T4]

计划把 `#shadow-player`（`position: fixed; bottom: 1.5rem`）放进 `#view-reader`。但 [style.css:358-371](../../static/style.css#L358-L371) 的 `readerUnfold` 动画 `fill-mode: forwards`，结束帧 `transform: translateY(0) scale(1)` 是**非 `none` 的 transform**——按 CSS 规范，非 none 的 transform 会使其成为 fixed 后代的 containing block。结果悬浮条锚定在阅读器盒子底部（长文末尾），滚动时不贴屏底，"常驻播控栏"整个失效；`left: 50%` 也变成相对 760px 阅读器而非视口。

**修复**：把 `#shadow-player` 移出 `.view`，作为 `<body>` 直接子元素，由 JS 依据当前视图控制显隐——顺带解决"非 reader 视图时隐藏"的需求。

---

## 三、主要缺陷（按任务）

### T1 URL 抓取

| # | 问题 | 证据 | 修复 |
| :- | :--- | :--- | :--- |
| 1 | **阻塞事件循环**：`ingest_from_url` 是 `async def`，却在里面同步调 `ingest_article → process_german_text → nlp(text)`（spaCy CPU 密集，新闻级文本数百毫秒到数秒）。FastAPI 在事件循环内联执行 `async def`，期间所有其他请求冻结。 | 计划 L105/L115；现有 `ingest` 端点特意用 `def`（[server.py:303](../../server.py#L303)）走线程池 | 改成普通 `def` 或 `await asyncio.to_thread(...)` |
| 2 | **测试不密闭、无断言**：`test_url_ingest_endpoint` 直接打真网 `example.com`，离线即挂，且没有任何 assert | 计划 L41-47 | `clean_html_to_text` 抽成纯函数用本地 fixture 测；网络层用 `httpx.MockTransport` 或 monkeypatch |
| 3 | **`source_url` 列白白存在**：schema 建了 `source_url`，计划从不写入——功能核心卖点（记住出处）丢失 | [server.py:31](../../server.py#L31) | `ingest_article` 增加 `source_url` 参数 |
| 4 | **接口说明与代码对不上**：Interfaces 声明输出含 `stats`、助手名 `extract_article_from_url`；实际代码返回 `{article_id,title,char_count}`、助手叫 `fetch_and_extract_url` | 计划 L33-34 vs L66-116 | 统一命名与输出契约 |

### T2 导入弹窗

| # | 问题 | 证据 | 修复 |
| :- | :--- | :--- | :--- |
| 1 | **拖拽是假的**：Interfaces 写了 `handleFileDrop(event)`，代码只实现点击→选文件，`dragover/drop` 从未绑定。真拖文件进 dropzone，浏览器默认行为是**离开页面打开该文件** | 计划 L142 vs L275-287 | 补 `dragenter/dragover/drop` 的 `preventDefault` |
| 2 | `submitActiveImport` 只分支 text/url；file tab 靠 `handleFileSelect` 切回 text 提交（逻辑能通），但按钮在 file tab 上点击静默无动作 | 计划 L251-273 | file tab 上也接提交动作 |
| 3 | 无编码探测：UTF-16 / Windows-1252 德语文件乱码 | — | 读文件时探测 BOM/编码 |
| 4 | 重选同一文件不触发 `onchange`，二次导入静默跳过 | 计划 L277 `e.target.files[0]` | onchange 后清空 input.value |
| 5 | `.modal-tab` 高约 24px，低于 design-system 的 36-44px 触控下限 | 计划 L206-217 | 提高触控热区 |

### T3/T4 播放器

| # | 问题 | 证据 | 修复 |
| :- | :--- | :--- | :--- |
| 1 | **`#speed-val` 不存在**：`setSpeed` 里 `document.getElementById('speed-val').textContent = ...`，但 T4 的 HTML 没有该元素 → **每次点语速抛 TypeError** | 计划 L427 vs L491-517 | 删该行或补元素 |
| 2 | 语速胶囊 active 态硬编码错：`0.8x` 按钮标 active 却调 `setSpeed(0.88)`；`setSpeed` 从不更新 `.active` | 计划 L425-429 / L511 / L626 | `setSpeed` 同步 `.speed-step-btn` 的 active |
| 3 | 快捷键全局劫持：只排除 INPUT/TEXTAREA，未排除 BUTTON——弹窗/抽屉开着时按 Space 同时触发聚焦按钮和播放器；全站 Space 滚动被掐死 | 计划 L643-659 | 排除 BUTTON；弹窗/抽屉打开时跳过 |
| 4 | `getVoices()` 首次调用返回空数组，无 `voiceschanged` 监听；找不到德语语音时静默回退默认（可能是中英文音色） | 计划 L366-368；现有 [app.js:17](../../static/app.js#L17) 同病 | 加 `voiceschanged`；音色缺失时明确提示 |
| 5 | 换文章时 `currentSentIdx` 不重置、旧 pauseTimer 泄漏 | — | `openReader` 时 reset 播放器状态 |
| 6 | Interfaces 声明 `playSentence/togglePlayPause/setPlaybackSpeed/nextSentence` 等，计划代码从未定义 | 计划 L304-311 | 统一命名 |

### T5 备份还原

| # | 问题 | 证据 | 修复 |
| :- | :--- | :--- | :--- |
| 1 | **restore 的 INSERT 列清单丢了三个真实列**：`articles.source_url`、`vocab_cards.plural`、`grammar_cards.examples_zh`。export 是 `SELECT *`，restore 用缺列清单 → 备份往返**静默丢数据** | 计划 L712/716/720 vs [server.py:27-64](../../server.py#L27-L64) | 列清单对齐真实 schema |
| 2 | **"全量还原"其实是合并**：只 `INSERT OR REPLACE`，本地有而备份没有的行永不删除 → 跨设备"迁移"残留旧数据 | 计划 L707-722 | 明确"合并 vs 全量替换"语义，提供 wipe-then-restore |
| 3 | **前端 UI 整体缺失**：Files 列表写了 `index.html`/`app.js`，但 Task 5 没有任何前端步骤——备份按钮、导出导入 JS 全没有 | 计划 L673-677 | 补前端步骤，或从 Files 列表删除 |
| 4 | restore 无测试；新增测试只 GET export 断言三个 key，从不 round-trip | 计划 L728-735 | 补 export→restore→校验往返测试 |
| 5 | 键冲突无策略：按原始整数 id `INSERT OR REPLACE`，跨设备合并产生孤儿卡片；且 [server.py](../../server.py) 从未 `PRAGMA foreign_keys=ON` | — | 定义 id 冲突/去重策略 |
| 6 | restore 载荷不校验：`RestoreReq` 用裸 `list`，缺 key 直接 KeyError→500 | 计划 L702-705 | 用 Pydantic 定义行模型 + `.get()` 兜底 |

### T6 启动器

| # | 问题 | 证据 | 修复 |
| :- | :--- | :--- | :--- |
| 1 | **`start.sh` 无可执行位**：Mac/Linux 双击 `./start.sh` 直接 Permission denied | 计划 L819-822，commit 步骤无 chmod | 提交时 `git update-index --chmod=+x start.sh` |
| 2 | **Termux 开箱即坏**：通常未装 uvicorn（无依赖安装步骤）；`webbrowser.open` 在 Termux 静默失败 | 计划 L797/L821 | 加依赖说明；Termux 用 `termux-open-url` |
| 3 | 端口 8000 占用时 `uvicorn.run` 抛 OSError 堆栈 | 计划 L800 | 启动前探测端口，友好提示 |
| 4 | **二维码承诺未兑现**：Goal 写明"打印局域网手机访问二维码"，`start.py` 无二维码代码，`requirements.txt` 无 `qrcode` 依赖 | 计划 L11 vs L758-804 | 补二维码，或从 Goal 删除承诺 |
| 5 | `get_local_ip` 失败时静默回退 `127.0.0.1`，打出的手机地址是废的；多网卡/VPN 下选错接口 | 计划 L773-781 | 枚举接口或检测失败提示 |

### T7 验收

| # | 问题 | 证据 | 修复 |
| :- | :--- | :--- | :--- |
| 1 | **密钥扫描是空壳**：Step 2 只有一句 "Scan working tree with regex."，无正则、无命令、无历史/悬空对象扫描、无 pre-commit 守卫 | 计划 L845 | 照搬 CLAUDE.md 已定义的正则与 `git fsck --no-reflogs` 流程 |
| 2 | **零 JS 自动化测试**：ShadowPlayer 状态机是全项目最复杂的逻辑，纯手动验收；"`pytest -v` → 100% PASS" 在线/离线都不成立 | 计划 L833-853 | 给状态机至少加一层自动化测试（纯逻辑抽函数 / jsdom 单测） |

---

## 四、跨任务的过度承诺 / 被低估点

1. **"脱机可用 + 跨平台 TTS" 言过其实**：Web Speech API 语音取决于浏览器/OS 自带音色。Android Chrome 的 `speechSynthesis` 经常语音列表为空或只有单一通用音色，德语音色不保证存在，离线更是无保证；Termux 上大概率"没有德语语音"。应加语音可用性检测 + 音色缺失提示，而不是宣称"确保脱机可用"。
2. **"卡拉OK逐句同步高亮"**：Web Speech API **没有词级边界事件**，词级卡拉OK 在声明栈下不可实现。计划实际做的是句级整句高亮——功能没问题，但命名与 Goal 措辞应对齐，别承诺做不到的事。
3. **计划内部接口命名自相矛盾**：`submitUrlImport/handleFileDrop/setPlaybackSpeed/playSentence/nextSentence/extract_article_from_url` vs 代码里的 `submitActiveImport/setSpeed/next/fetch_and_extract_url`。Subagent 严格照 Interfaces 写会直接产出死代码。实施前必须统一。
4. **DW / Tagesschau / Spiegel 的抓取现实**（被验证器驳回，但真实风险）：Spiegel 有 Cloudflare + 付费墙、DW 有反爬，纯 `httpx + 手写正则` 大概率拿到验证页或摘要。建议用 `trafilatura` / `readability-lxml` 替代手写 `clean_html_to_text`（纯 Python，不破坏"零 Node"约束），并在开发期对目标站点逐一实测。

---

## 五、实施前必改清单（浓缩）

1. **T1**：补 `Tuple`/`datetime` 导入；SSRF 校验；`async def` 改 `def`；`source_url` 入库；测试改用 fixture + MockTransport。
2. **T2**：补 `dragover/drop` 的 `preventDefault`；加编码探测。
3. **T3**：`onerror` 过滤 `interrupted/canceled`；删 `#speed-val` 引用或补元素；加 `voiceschanged`；切换文章时重置状态。
4. **T4**：播放器移出 `#view-reader`（或去掉动画的 `forwards` transform）；键盘处理排除 BUTTON 与弹窗打开状态；修语速胶囊 active 态。
5. **T5**：restore 列清单对齐真实 schema；补备份前端 UI 或从 Files 列表删除；明确"合并 vs 全量替换"；补 round-trip 测试；加令牌鉴权。
6. **T6**：`chmod +x`；端口冲突提示；Termux 依赖说明；补二维码（或从 Goal 删除）；0.0.0.0 绑定加鉴权说明。
7. **T7**：密钥扫描填入真实正则与命令；给 ShadowPlayer 状态机加自动化测试。

---

## 六、结论

本计划的技术方向与现有代码库一致，具备实施价值。但**必须先处理第二、三节的阻断级与主要缺陷**，否则会出现：LAN 上可被远程覆盖/读取的裸库、播放器跳句即停、悬浮条不悬浮、备份还原静默丢数据、启动器在 Mac/Linux 上双击即 Permission denied 等"做完即坏"的结果。建议按第五节清单逐项修订后，再进入实施。
