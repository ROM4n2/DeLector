# 设置信息架构与思考强度控件调研

> 日期：2026-11-07　|　性质：只读调研 + 方案（不改 `static/`、不跑 pytest）　|　范围：设置双入口、模型名事实核查、思考强度控件
> 证据标记：`[A]` 本机实测（computed style / DOM 量测 / 截图）｜`[A-capture]` 用户截图原始像素量测｜`[B]` 官方文档｜`[U]` 未验证

---

## 0. 结论先行

1. **模型名不能改成 `deepseek-flash`。** `deepseek-v4-flash` 不是过时的显示文案，而是真正发给 `/chat/completions` 的 `model` 字段默认值；DeepSeek 官方文档在 2026-11-07 仍只列出 `deepseek-v4-flash` 与 `deepseek-v4-pro`，没有 `deepseek-flash`。改名会让请求直接失败（400/422），不是「显示不对」。
2. **两个设置入口不是「高度重叠」，是 100% 同一个弹层。** 顶部导航「设置」(`index.html:101`) 与移动端 dock「设置」(`index.html:3218`) 都调用同一个 `openSettingsModal()`；在 ≤1024px 时两者同屏出现，因此移动端一屏能看到两个「设置」。
3. **思考强度控件目前是「装饰性」的。** Python 出网口 `llm_client.chat()` 的 payload 只有 `model/messages/max_tokens(+temperature/response_format)`，没有 `thinking` 或 `reasoning_effort`；Go 伴学 Agent 虽然从请求里收了 `reasoning_effort`，但只写进 trace，`streamReq` 没有把它发给模型。**改控件外观之前，必须先决定是否真的把它接通。**
4. **四档与官方语义对不上。** 官方思考强度只有 `high` / `max`；`low`、`medium` 会被映射为 `high`，`xhigh` 映射为 `max`；关闭思考是另一个开关 `{"thinking":{"type":"disabled"}}`。因此「极速/平衡/深度」三档里有两档在 API 层是同一件事。
5. **推荐设置 IA：每个断点只保留一个入口 + 三段分组。** 移动端只留 dock 入口，桌面端只留顶部入口；弹层重排为「AI 与思考强度 / 德语发音 / 关于与数据（可选）」三段，思考强度改为整行控件，不再塞进半列。
6. **推荐思考控件：三档整行 segmented control（关闭 / 标准 / 深读），点一下立即生效。** 393 与 360 下每段约 92–102px 宽、44px 高，短标签 2 字，选中项下方只显示一行描述；不再使用原生 `<select>`，也不再给每个选项挂两行长描述。
7. **附带发现（不在本次改动范围）：** Go 侧默认模型常量仍是 `deepseek-flash`，仅在 Python supervisor 注入 `API_MODEL` 时才被覆盖；独立启动 Go Agent 会落到官方未列出的名字。建议另开小修，不与设置重构混在一起。

---

## 1. 方法与边界

### 1.1 本次做了什么

- 静态阅读：`static/js/main.js`、`static/modals/settings_modal.html`、`static/layout/*`、`static/style.css`、`delector/core/db/settings.py`、`delector/services/llm_client.py`、`agent/` 相关请求链路。
- 本机实测：用 Edge headless + CDP 在 393×852 与 360×780 下渲染设置弹层，读取 `getBoundingClientRect()` / `getComputedStyle()` 并截图。脚本是临时文件，不入库。
- 用户截图量测：对 `user-native-select-393.png`（486×1011）做像素采样，测原生选择层边界与行高；原生弹层是 OS/浏览器绘制的，DOM 无法量测，因此单独标 `[A-capture]`。
- 官方文档核对：DeepSeek「模型 & 价格」「Lists Models」「思考模式」「错误码」，均于 2026-11-07 抓取。

### 1.2 本次没做什么

- 没有修改 `static/` 下任何文件；没有跑 pytest；没有碰 ADR、计划、`WORKMEMORY`。
- 没有调用真实 DeepSeek API（没有用用户 Key 发请求）；模型名结论来自官方文档 + 代码链路，不来自计费调用。
- 没有实现控件，也没有改 Go/Python 请求。

### 1.3 复现命令

```powershell
node d:\Code\DeLector\_artifacts\2026-11-07-settings-shots\measure.mjs
```

截图与原始 JSON 在 `_artifacts/2026-11-07-settings-shots/`（未跟踪，不提交 git）。

---

## 2. 模型名：先查事实

### 2.1 代码链路：它是真请求字段，不是显示标签

| 位置 | 角色 | 值 | 是否影响真实请求 |
|---|---|---|---|
| `delector/core/db/settings.py:107-108` | 默认模型（DB 无值时兜底） | `deepseek-v4-flash` | **是**。`get_effective_api_model()` 的返回值被 supervisor 注入 `API_MODEL` |
| `delector/core/go_agent_supervisor.py:169-171` | 把 DB 值写进 Go 子进程环境 | `env["API_MODEL"] = eff_model` | **是**。Go 用它覆盖默认模型 |
| `delector/services/llm_client.py:196-230` | Python 唯一出网口 | `payload["model"] = model` | **是**。Python 侧所有 AI 剖析/润色都走这里 |
| `agent/cmd/delector/agent.go:51-53` | Go 启动时用 `API_MODEL` 覆盖默认 | `model = os.Getenv("API_MODEL")` | **是**。标准部署下实际模型是 DB 值 |
| `static/modals/settings_modal.html:131,146` | 输入框 placeholder 与预设 pill | `deepseek-v4-flash` | 否（用户可改；保存后进入 DB，随后影响请求） |
| `static/js/main.js:708` | 设置弹层加载失败时的前端兜底 | `deepseek-v4-flash` | 否（仅回显） |
| `agent/internal/provider/provider.go:25-27` | Go 默认模型常量 | `deepseek-flash` | **条件性**：只有 Go 独立启动、且没有 `API_MODEL` 时才生效 |

结论：`deepseek-v4-flash` 出现在「真请求字段 + 默认值 + 回显」三层；不是单纯的 UI 文案。用户想改的 `deepseek-flash` 恰好与 Go 侧默认常量同名，但这不代表它是官方当前标识。

### 2.2 官方当前模型标识（2026-11-07）

| 标识 | 官方状态 | 说明 |
|---|---|---|
| `deepseek-v4-flash` | **当前可用** | 官方「模型 & 价格」表第一列；1M 上下文、最大 384K 输出；支持思考/非思考 |
| `deepseek-v4-pro` | **当前可用** | 官方表格第二列；价格更高、并发更低 |
| `deepseek-chat` | 已弃用（2026-07-24 23:59 起） | 兼容映射到 `deepseek-v4-flash` 的非思考模式 |
| `deepseek-reasoner` | 已弃用（2026-07-24 23:59 起） | 兼容映射到 `deepseek-v4-flash` 的思考模式 |
| `deepseek-flash` | **官方未列出** | 在「模型 & 价格」与 `GET /models` 示例中都找不到；`[U]` 是否存在未公开别名 |

来源：
- 模型与价格：<https://api-docs.deepseek.com/zh-cn/quick_start/pricing>（2026-11-07 抓取）
- 模型列表：<https://api-docs.deepseek.com/api/list-models>（示例只列 `deepseek-v4-flash` / `deepseek-v4-pro`）
- 错误码：<https://api-docs.deepseek.com/zh-cn/quick_start/error_codes>（400 格式错误 / 422 参数错误）

### 2.3 改名的风险与结论

**能不能改：不能把值改成 `deepseek-flash`。** 如果只改 UI 显示、不改值，可以；如果改的是 `model` 字段，请求会以 400/422 失败，表现是「AI 剖析突然全部不可用」，而不是「名字看起来不对」。

推荐处理：

1. **保留值 `deepseek-v4-flash`**，不在本次重构中改默认模型。
2. 若只是觉得 `v4` 显得旧，把 **label/预设文案**改成官方展示名 `DeepSeek-V4-Flash`，值保持不变；这是零风险改动。
3. **不要为 `deepseek-flash` 加客户端兼容映射**。客户端无法知道上游是否接受别名；若将来官方真的提供别名，应以后端白名单/配置项形式加，并在设置页显示「官方标识」。
4. Go 侧 `DeepSeekDefaultModel = "deepseek-flash"` 与官方标识不一致，属于独立技术债；标准部署被 `API_MODEL` 掩盖，独立启动才会暴露。建议单开小修，不与本次设置重构绑定。

---

## 3. 设置信息架构现状

### 3.1 两个入口打开的是同一个东西

| 入口 | 断点 | 代码位置 | 行为 |
|---|---|---|---|
| 顶部导航「设置」 | 所有宽度（含移动端） | `static/layout/nav_desktop.html:50-56` → `openSettingsModal()` | 打开 `#settings-overlay` |
| 移动端 dock「设置」 | ≤1024px | `static/layout/nav_mobile.html:52-58` → `openSettingsModal()` | 打开同一个 `#settings-overlay` |

- `openSettingsModal()` 定义在 `static/js/main.js:693`；两个入口没有参数、没有分支。
- 移动端 dock 有 8 项，设置是第 8 项；顶部导航在 ≤1024px 时仍保留 `.nav-actions`，所以「拆句 / 设置 / 导出 Anki」与 dock 同屏。
- 实测 393×852 与 360×780 下 `navSettingsVisible` 均为 `true`，dock 设置项均可见 → **移动端确实有两个同功能入口**。

### 3.2 弹层内容清单（当前只有两组）

| 分组 | 条目 | 控件 | 393 宽 × 高 | 360 宽 × 高 | 备注 |
|---|---|---|---|---|---|
| AI 深度剖析服务 | API Key | password + 显示按钮 | 251.7×43 | 222×43 | 独占一行 |
| | Base URL | text + 2 个预设 pill | 145.8×43 | 131×43 | 半列 |
| | Model | text + 1 个预设 pill | 145.8×43 | 131×43 | 半列；预设 pill 会换成两行 |
| | 思考强度 | 原生 `<select>` | 145.8×45 | 131×45 | 半列；**本次重点** |
| | 测试连通性 | button + 状态文本 | — | — | 在折叠线附近 |
| 德语发音与 TTS | Voice | 原生 `<select>` | 145.8×45 | 131×45 | 半列 |
| | Speed | 原生 `<select>` | 145.8×45 | 131×45 | 半列 |
| 底部 | 取消 / 保存并生效 | buttons | — | — | 393/360 均在初始视口外 |

- 弹层外壳：`max-width:540px`、`width:90vw`、`padding:24px`、`max-height:90vh`、`overflow-y:auto`（`static/style.css:2529-2542, 7573-7580`）。
- 字段：`padding:12px 14px`、`font-size:14px`、`border:1.5px`（`static/style.css:2703-2716`）。
- 标签：mono、10.4px、字距 0.14em、全大写（`static/style.css:2140-2151`）。

### 3.3 本机实测（393 / 360）

| 指标 | 393×852 | 360×780 |
|---|---|---|
| 弹层尺寸 | 353.7×766.8（90vh） | 324×702（90vh） |
| 弹层内容高度 | 856 | 925 |
| 需要滚动 | **91px（10.6%）** | **225px（24.3%）** |
| API Key 宽 | 251.7 | 222 |
| 双列字段宽 | 145.8 | 131 |
| 思考强度控件宽 | 145.8 | 131 |
| Voice/Rate 初始 y | 755（接近底部） | 820.4（**已在折叠线外**） |
| 顶部「设置」按钮 | 48×36，可见 | 48×36，可见 |
| dock 单项 | 49.1×57 | 45×57 |
| dock 项数 | 8 | 8 |

360 下还有一个双列错位：Base URL 标签换成两行，输入框 y=368.2；Model 标签一行，输入框 y=354.2。两列不在同一基线上，视觉上像「Model 浮起来了」。

### 3.4 原生选择层实测（用户截图，`[A-capture]`）

截图原图 486×1011：

| 指标 | 数值 |
|---|---|
| 弹层横向范围 | x=12–476，宽 **465px（95.7% 屏宽）** |
| 弹层纵向范围 | y=335–671，高 **337px（33.3% 屏高）** |
| 四行高度 | 335–417 / 420–502 / 505–587 / 589–671，每行 **83px** |
| 行间分隔 | 2px 浅灰缝 |
| 文字与 App 字体关系 | 弹层文字明显大于表单标签（标签约 16px 量级），完全脱离 App 的编辑式排印 |

结论：这不是「一个下拉框稍微大一点」，而是**另一个视觉系统**盖在 App 上。用户说的「出戏」是准确的。

### 3.5 结构问题清单

1. **同屏双入口**：移动端顶部 + dock 各一个「设置」，且行为完全相同。
2. **单弹层过长**：两组设置塞进 90vh 弹层，393 需滚 91px，360 需滚 225px；保存按钮在首屏外。
3. **半列塞重控件**：思考强度是本次要改的主角，却被塞进 131–146px 的半列；关闭状态下选中文案被截断，提示文字被挤成 3 行。
4. **360 双列基线错位**：标签换行导致两个输入框不在同一行。
5. **控件重复**：伴学抽屉底部已有 3 个「思考强度胶囊」（`.thinking-pill` 标记见 `static/modals/drawer.html:386-389`，同步逻辑见 `static/js/cp-drawer.js:250-270`），设置里又有一个 4 档 select；两者状态单向同步，选 `none` 时抽屉没有任何胶囊高亮。
6. **视觉语言不统一**：通用 `.modal` 是 1.5px 墨线 + 6px 硬阴影 + 10px 圆角；`settings-modal-box` 覆盖成 8px 圆角 + 柔和阴影，边框仍继承墨线。
7. **无「关于/数据」**：当前设置只有 AI 与 TTS；备份/恢复在卡片页（`static/index.html` 的备份按钮），导出 Anki 在顶部导航，信息架构上「设置」并不完整。

---

## 4. 外部参考

### 4.1 取证方式与限制

- 本机无头浏览器**直连出网被重置**（`ERR_CONNECTION_CLOSED`），因此改用本地代理 `127.0.0.1:7897` 启动 Edge headless（393×852），对官方帮助页截图；截图在 `external/`。
- **能截到的是官方帮助页，不是 App 内界面**。ChatGPT / Claude / Notion / Cursor 的 App 都需要登录，无法在不输入任何凭据的前提下进入设置页；因此下表的 IA 事实来自官方文档与官方发布说明，标 `[B]`，不冒充 App 实测。
- YouTube 移动网页、DeepL、LM Arena 在直连/代理下均未能稳定渲染，标 `[U]`，不填任何数字。
- 行高没有产品级实测值，统一留 `—`；只引用平台基线：Apple HIG 44pt、Material 48dp。

### 4.2 外部对照表

| 产品 | 设置入口 | 分组层级 | 思考/推理控件 | 关键事实 | 证据 | 截图 |
|---|---|---|---|---|---|---|
| **ChatGPT** | 对话顶部/模型选择器（iOS/Android） | 单层菜单 | 菜单内 **Instant / Medium / High / Extra High**（Pro 另有 Pro Standard / Pro Extended） | 推理强度不放在全局设置，而是模型选择器；选中项常驻输入区上方 | `[B]` 官方发布说明 | Cloudflare 拦截，未留图 |
| **Claude** | 发送按钮旁的模型菜单 | 模型菜单内含 3 组：模型 / Effort / Thinking | **Effort 子菜单**：Low / Medium / High / Extra high / Max，推荐档标 `Default`；**Thinking 是独立开关** | 改完从下一条回复生效，**没有全局保存按钮**；effort 与 thinking 可任意组合 | `[B]` 官方帮助 | `claude-extended-thinking-393.png` |
| **Cursor** | 模型选择器 / 模型配置 | 单层 | **Min/Low、Medium、High/Max** 等档位，在模型配置中调整；Bugbot 另有 High/Custom | 推理投入与模型绑定，不在全局 Settings 里 | `[B]` 官方 changelog + 社区说明（主聊天 UI 未实测） | `cursor-effort-changelog-393.png` |
| **Cline** | Cline 面板右上角齿轮 | 单面板，无二级页 | 选完模型后，下方 **Enable Extended Thinking** 复选框 | 设置与模型选择同屏；没有独立「思考强度」滑杆 | `[B]` 官方文档 | `cline-anthropic-provider-393.png` |
| **Open WebUI** | Settings / Model controls | Settings 内分 General、Interface、Models 等 | **Temperature / Top P 等为滑杆或数字输入**；管理员可在 Workspace → Models 设默认值 | 参数按「全局默认 → 单模型 → 单对话」三级覆盖 | `[B]` 官方文档 | `openwebui-models-393.png` |
| **Notion** | 桌面：左侧栏顶部 **Settings & members**；移动：侧栏 **Notifications & settings** | 设置页内按区块分组（账号、外观、通知等），移动端滚动到对应区块 | 无推理控件 | 单一入口 + 分组列表；移动端入口在侧栏而不是底部 dock | `[B]` 官方帮助 | `notion-account-settings-393.png` |
| **Things 3** | App 内 Settings 齿轮 | 二级：Settings → Appearance / Calendar Events / Things Cloud / Reminders Inbox 等 | 无推理控件 | 左上进入、右上 `Close` 关闭；分组列表 + 开关/滑杆 | `[B]` 官方支持文档 | `things-settings-393.png` |

来源（均于 2026-11-07 抓取）：

- ChatGPT 发布说明：<https://help.openai.com/zh-hant/articles/6825453-chatgpt-release-notes>（模型选择器一段来自该页摘要）
- Claude：<https://support.claude.com/en/articles/8664678-change-the-model-effort-and-thinking-settings>
- Cursor：<https://cursor.com/changelog/05-11-26>；模型选择器交互另见 <https://forum.cursor.com/t/cursor-update-3-1-17-limits-all-model-choices-to-thinking/158568>
- Cline：<https://docs.cline.bot/provider-config/anthropic>
- Open WebUI：<https://docs.openwebui.com/features/workspace/models/>
- Notion：<https://www.notion.com/help/account-settings>
- Things 3：<https://culturedcode.com/things/support/articles/2803583/>

`[U]` 未验证：

| 产品 | 尝试结果 | 原因 |
|---|---|---|
| YouTube 移动网页 | 未取得播放器齿轮菜单量测 | 出网被重置，页面未稳定渲染 |
| DeepL 翻译 | 未取得设置面板量测 | 出网被重置 |
| LM Arena | 未取得 Settings 面板量测 | 出网被重置 / 反自动化 |

### 4.3 外部参考给出的 6 条结论

1. **同一屏不会出现两个「设置」入口。** 在这 7 个产品里，桌面与移动可以各有一个入口，但同一屏只看到一个；没有产品把「设置」同时放在顶栏和底部 tab。
2. **设置根是「单一入口 + 分组列表」。** Notion、Things 都是这个结构；移动端入口在侧栏/齿轮，不在底部导航里挤第 8 项。
3. **推理强度属于「模型/输入区」，不属于全局设置。** ChatGPT 放在对话顶部模型选择器；Claude 放在发送按钮旁；Cursor 放在模型配置。用户是在「这次要花多少思考」的语境里改它，而不是去设置页找。
4. **档位用短标签 + 单行说明，不用两行长描述。** Claude 的 Effort 菜单是 Low/Medium/High/Extra high/Max，推荐档用 `Default` 标记；没有给每一档写两行解释。
5. **「思考开关」与「思考强度」可以是两个控件。** Claude 明确把 Thinking 做成 toggle、把 effort 做成子菜单；ChatGPT 则用 Instant 表示「不思考」，用 Medium/High/Extra High 表示强度。两者都说明：**关闭思考不是强度的一档，而是另一个维度**。
6. **改完立即生效，不要求再点保存。** Claude 明确「从下一条回复生效」；这对我们「点一下就能选」的目标是直接支持。

### 4.4 对我们的直接映射

| 外部做法 | 我们的建议 |
|---|---|
| 单一设置入口 | 每个断点只留一个「设置」入口（方案 A） |
| 推理控件靠近模型/输入区 | 短期留在设置弹层，但必须整行、短标签；长期可把「模型 + 思考强度」做成输入区上方的快捷条 |
| 短标签 + 单行说明 | `关闭 / 标准 / 深读` + 选中项一行说明 |
| Thinking 与 Effort 分离 | 用三档预设（关 / 标准 / 深读）表达同一组组合，避免四档伪精度 |
| 立即生效 | 点选即保存，不参与底部 Save/Cancel |
| 分组列表而非长表单 | 方案 A 先分三段；设置项继续增长则转方案 B 的独立设置页 |

---

## 5. 设置信息架构方案

### 5.1 方案 A（推荐，改动最小）：每个断点一个入口 + 三段分组

**入口收敛**

- 桌面（>1024px）：保留顶部「设置」，dock 不显示。
- 移动（≤1024px）：**隐藏顶部「设置」按钮**，只保留 dock 最后一项。
- 不新增「我的」页，不引入二级抽屉，不改现有 `openSettingsModal()` 的调用协议。

**弹层分组**

| 分组 | 内容 | 说明 |
|---|---|---|
| AI 与思考强度 | API Key、Base URL、Model、思考强度、测试连通性 | 把「思考强度」从半列提到整行，放在 Model 下方 |
| 德语发音 | Voice、Speed | 与 AI 无关，保持独立；可即时保存 |
| 关于与数据（可选，二阶段） | 版本号、NLP 引擎状态、备份/恢复入口、导出 Anki | 现有功能散落在卡片页/顶部导航，是否迁入需产品确认 |

**旧入口怎么处理**

- 移动端顶部按钮隐藏，不是删除 DOM；桌面端仍可用。
- 更新 `FEATURES.md` 中「无论在桌面端顶部导航栏还是移动端底部 Dock」的描述，避免文档与实现漂移。
- 保留 `openSettingsModal()` 作为唯一打开函数，未来换成设置页时只改这一处。

**优点**：改动集中在 CSS 断点 + 一个按钮的可见性 + 弹层内分组；风险低，可独立回滚。
**缺点**：仍是 90vh 长弹层；分组只是视觉分区，没有解决「设置项变多」的问题。

### 5.2 方案 B（目标形态）：设置改为独立视图，单一 dock 入口

- 设置成为与「文库/台账/…」并列的 view，不再是 modal；移动端从 dock 进入，桌面端从顶部进入。
- 页面内用「分组标题 + 行式条目」，每行左侧标签、右侧当前值，点条目进入二级页（AI / 发音 / 数据 / 关于）。
- 优点：空间充足，符合 iOS 设置/Things 的成熟心智；未来加「关于/数据」不需要再挤弹层。
- 缺点：需要新增 view 路由、返回栈、深链接与样式；工作量明显大于方案 A。

### 5.3 方案 C（不推荐）：保留两个入口，但拆职责

- 顶部「设置」只放 AI 快捷项（模型 + 思考强度 + 音色），dock 放完整设置。
- 优点：高频项一屏可达。
- 缺点：仍然有两个「设置」字样；用户需要先理解「哪个设置更全」，与本次「去重」目标相反。除非把顶部改名为「AI」并换图标，否则不建议。

### 5.4 推荐

**先做 A，把 B 作为设置项增长后的目标。** 本次只改视觉与入口可见性，不动数据结构；等「关于/数据」真的要迁入时，再评估 B。C 不采纳。

---

## 6. 思考强度控件方案

### 6.1 现状：不仅是原生控件出戏，语义也没接通

**UI 侧**

- 设置弹层：4 档 `<select>`，每个选项带两行长描述；半列宽 131–146px，关闭状态只显示被截断的「平衡 (Medium)」。
- 伴学抽屉：3 个 `.thinking-pill`（极速/平衡/深度），默认 `medium`，高度约 20px，触达面积远小于 44px。
- 两处状态：`setReasoningEffort()` 会同步 select 与胶囊；但 `none` 没有对应胶囊，选「关闭思考」后抽屉无高亮。

**后端侧**

| 路径 | 是否发送思考参数 | 证据 |
|---|---|---|
| Python `llm_client.chat()` | **否** | payload 只有 `model/messages/max_tokens`，可选 `temperature/response_format`（`llm_client.py:226-234`） |
| Go 伴学 `streamReq` | **否** | `openai.ChatCompletionRequest` 只设置 `Model/Messages/Tools/ToolChoice/Stream`（`agent/internal/companion/loop.go:376-382`） |
| Go trace | **是，仅记录** | `ReasoningEffort` 写入 `TurnTraceRecord`（`pipeline.go:145-149`） |
| Go 启动参数 | **读到但未使用** | `agent.go:58-63` 读取 env 后，未传入 Agent 构造或请求 |

**官方语义**

- 思考开关：`{"thinking":{"type":"enabled/disabled"}}`，默认 `enabled`。
- 思考强度：`{"reasoning_effort":"high/max"}`；`low`、`medium` 映射为 `high`，`xhigh` 映射为 `max`。
- 复杂 Agent 请求默认 `max`；普通请求默认 `high`。
- 思考模式下 `temperature/top_p` 等参数不生效。

因此当前四档实际只有两种可表达状态：**开（high）** 与 **关**；「极速/平衡」在 API 层没有区别，「深度」也只是 high 的另一个说法，除非真的发 `max`。

### 6.2 方案 A（推荐）：三档整行 segmented control

**形态**

```
思考强度
[ 关闭 ] [ 标准 ] [ 深读 ]     ← 三档等宽，整行，44px 高，点一下即选
标准：常规语法场域分析           ← 仅显示当前选中项的一行描述（12px）
```

**为什么是三档而不是四档**

- 官方只有 `high` / `max` 两个强度 + 一个关闭开关；三档预设与 DeepSeek 实际可用的三种组合（关 / high / max）一一对应。
- 外部产品把 Thinking 与 Effort 做成两个独立控件（Claude），或用 Instant 表示不思考（ChatGPT）。我们压成三档预设，会失去「开 + Low/Medium」这类组合；但 DeepSeek 的 `low`、`medium` 本来就会映射为 `high`，实际可用组合只有三种，因此三档不会丢失真实能力。
- 四档会让「极速/平衡」变成无法兑现的承诺；如果保留四档，至少要在文案上承认它们相同，这比三档更难解释。

**取值映射（兼容现有 DB，不改 schema）**

| UI | 存储值 | 发给 API |
|---|---|---|
| 关闭 | `none` | `thinking: {type:"disabled"}`；不传 `reasoning_effort` |
| 标准 | `medium`（沿用现有默认） | `reasoning_effort:"high"` |
| 深读 | `high` | `reasoning_effort:"max"` |

- 旧值 `low` 视为 `medium` 处理，读取时归一化；旧值 `high` 继续表示「深读」，不降低用户已有的强度预期。
- 这样不需要迁移数据库，也不会让已有用户的选择失效。

**393 / 360 具体排布**

| 视口 | 弹层内容宽 | 每段宽（3 等分，含边框） | 控件高 | 标签字号 | 说明 |
|---|---|---|---|---|---|
| 393 | 305.7px | ≈101.9px | 44px | 12px mono | 「关闭/标准/深读」2 字，左右各余 ~40px |
| 360 | 276px | ≈92px | 44px | 12px mono | 同上，仍不换行 |

- 不需要横向滚动，不需要缩小字号。
- 选中态：`background: var(--ink); color: var(--paper)`；未选中：透明底、`var(--pencil)`；切换 180ms `--dur-fast` + `--ease-editorial`（与 `.cards-seg-btn` 同档，见 `static/style.css:3713-3754`）。
- 控件用 `role="radiogroup"` + 三个 `role="radio"` / `aria-checked`，键盘左右方向键可切换；不要只靠颜色表达选中态。

**长描述放哪**

- **不做**每个选项常驻两行描述；只保留选中项的一行说明，放在控件下方，12px、`var(--pencil)`、单行。
- 文案建议：
  - 关闭：`不输出思维链，响应最快`
  - 标准：`常规语法场域分析`
  - 深读：`长难句 / 德福级推演`
- 这三条在 276px 宽、12px 字号下都能单行放下（约 13–15 个汉字）。

**是否记住上次选择**

- 记住，沿用现有 `/api/settings` 的 `REASONING_EFFORT` 持久化。
- 点选即保存（与抽屉胶囊一致），控件旁给一个 1.5s 的「已保存」微提示；不要让它参与底部「保存并生效」的事务，否则用户点「取消」会不知道刚才那一下算不算数。
- 抽屉胶囊与设置控件共享同一个状态源；选「关闭」时抽屉显示一个明确的「关闭」胶囊，而不是全部熄灭。

**是否即时生效**

- 即时保存 + 即时生效。若后端尚未接通（见 6.4），先按 6.4 接通再上线，避免「控件很顺滑但行为没变」。

### 6.3 方案 B：四档 segmented（保留现有文案）

- `[关闭][极速][平衡][深度]` 四等分：393 每段 ≈74px，360 每段 ≈65px，2 字标签仍可放下。
- 优点：与现有四档文案连续，用户不需要重新学习。
- 缺点：必须决定「极速/平衡」是否真的发不同参数；若都映射 high，就是四个按钮两种效果，属于伪精度。**除非产品明确要保留四档叙事，否则不推荐。**

### 6.4 方案 C：自定义 popover 列表（保留长描述）

- 点击后弹出自绘列表，每行「档位名 + 一行描述」，不用系统选择层。
- 优点：保留解释性文案；视觉可控。
- 缺点：仍是「点一下 → 再点一下」，没有解决用户要的「点一下就能选」；且弹层会遮挡表单。**不推荐。**

### 6.5 接入实现要点（未来实现时）

1. **Python**：`llm_client.chat()` 增加可选 `reasoning_effort` / `thinking` 参数，写入 payload；关闭时发 `thinking:{type:"disabled"}`，标准发 `reasoning_effort:"high"`，深读发 `"max"`。调用方从 `get_effective_reasoning_effort()` 读取。
2. **Go**：`streamReq` 增加 `ReasoningEffort` 与 `Thinking` 字段（若 `go-openai` 结构不支持，使用自定义请求结构或 `ExtraBody`）；不要只写 trace。
3. **前端**：删除设置里的 `<select>`，换成 segmented；同步更新 `cp-drawer.js` 的胶囊为同一三档（增加「关闭」），并移除 `transition: all`（`style.css:12211-12222`，`transition: all` 在 12219）改为具体属性过渡。
4. **契约测试**：断言三个 UI 状态分别产生 `thinking disabled`、`reasoning_effort=high`、`reasoning_effort=max`；断言旧值 `low` 归一化为 `medium`；断言设置与抽屉双向同步。
5. **可观测**：trace 里的 `reasoning_effort` 应记录实际发送值（high/max/disabled），而不是 UI 原始值。

---

## 7. 明确不做

- 不改 `static/` 任何文件；本文件只出方案。
- 不把模型值改成 `deepseek-flash`；不为它加客户端别名映射。
- 不改 Go 默认模型常量（另开小修）。
- 不引入 slider：三档离散值用滑杆没有收益，反而增加拖动精度与无障碍成本。
- 不保留「四档 + 两行长描述」的原生 select 作为 fallback；自定义控件本身就是替代。
- 不在本次迁移「备份/恢复/关于」；这些需要单独确认信息架构与数据风险。
- 不做图标集 vendor、角色 SVG 化、卡片空态等挂账项。
- 不跑 pytest、不开模拟器、不改 ADR/计划/WORKMEMORY。

---

## 8. 未来实现的验收判据

| 项 | 判据 |
|---|---|
| 入口唯一性 | 393 与 360 下同屏「设置」入口数 = 1；桌面 >1024 下 = 1 |
| 弹层可读性 | 393 与 360 下思考强度控件整行显示，选中文案不被截断 |
| 触达尺寸 | segmented 每段 ≥44px 高；dock 项 ≥44×44 |
| 交互 | 单击即选中，无系统选择层；键盘方向键可切换；`aria-checked` 正确 |
| 状态一致性 | 设置控件与抽屉胶囊任一变更，另一处 500ms 内同步；`none` 有明确选中态 |
| 请求契约 | 关闭 → `thinking.disabled`；标准 → `reasoning_effort=high`；深读 → `reasoning_effort=max` |
| 兼容 | 旧值 `low/medium/high` 读取不报错；`high` 仍表现为「深读」 |
| 模型名 | 保存后请求体 `model` 仍为 `deepseek-v4-flash` |

---

## 9. 证据清单

| 文件 | 内容 |
|---|---|
| `_artifacts/2026-11-07-settings-shots/current-settings-393.png` | 393×852 设置弹层（含顶部设置按钮与 dock） |
| `_artifacts/2026-11-07-settings-shots/current-settings-360.png` | 360×780 设置弹层 |
| `_artifacts/2026-11-07-settings-shots/current-settings-393-full.png` | 393 全页截图（含折叠线以下内容） |
| `_artifacts/2026-11-07-settings-shots/current-settings-360-full.png` | 360 全页截图（含折叠线以下内容） |
| `_artifacts/2026-11-07-settings-shots/current-shell-393.png` | 393 无弹层外壳，顶部与 dock 双入口同屏 |
| `_artifacts/2026-11-07-settings-shots/measurement-393.json` | 393 下全部 DOM 尺寸 |
| `_artifacts/2026-11-07-settings-shots/measurement-360.json` | 360 下全部 DOM 尺寸 |
| `_artifacts/2026-11-07-settings-shots/user-native-select-393.png` | 用户提供的原生选择层截图（486×1011） |
| `_artifacts/2026-11-07-settings-shots/harness.html` | 静态复现页（只引用 `static/style.css`，不改源码） |
| `_artifacts/2026-11-07-settings-shots/measure.mjs` | CDP 量测/截图脚本（临时，不入库） |
| `_artifacts/2026-11-07-settings-shots/measure_popup.py` | 原生弹层像素量测脚本（临时，不入库） |
| `_artifacts/2026-11-07-settings-shots/external/` | 外部参考截图与原始记录（见 §4） |

> `_artifacts/` 为未跟踪证据目录，不提交 git；截图仅用于本次评审。
