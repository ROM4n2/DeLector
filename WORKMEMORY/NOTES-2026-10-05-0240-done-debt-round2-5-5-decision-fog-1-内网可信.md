### 2026-10-05 02:40 | codebuddy | DONE(debt-round2, 5/5) + DECISION(Fog-1: 内网可信)

> 本文件是 `WORKMEMORY/work.log` 中该事件的**正文**（原事件 5056 B，超 `PROTOCOL.md` §4 的 4096 B 上限）。
> 拆分时间：2026-10-14；正文逐行无损搬运，未删改任何内容。

Caps: filesystem-read, filesystem-write, shell-exec
事件：`docs/plans/2026-10-05-debt-round2-guards.md` 的 5 个 Task 全部完工并合入 master（`333623c`）。**Fog 1 已由用户裁决：内网可信 ⇒ 不加固 LAN 写端点。**
- **PR #103**（`tests/test_localhost_guard.py` +129）：把「哪些端点挂 `_require_localhost`」从注释变成红灯守卫。AST 实测全集 **20 个**（`main.py` 16 函数体内调用 + `encounter.py` 3 + `tools.py` 1 `Depends` 形式）——注释里的"16"已漂移。判据 MUST 是**精确 allowlist 相等**而非"GET 不该挂闸"（有 4 个**受保护的敏感 GET**：`/api/backup/export`、`/api/backup/download/{token}`、`/api/wb/backup/download/{token}`、`/api/wb/state/key`）。
- **PR #104**（改 `static/`）：工作台来源判据**单点化**，`cardStatsTag` 第 242 行改为调 `isWorkbenchSourced`。E1 从"两份文本雷同"改为"**复用且禁止双写**"（`MUST 出现 isWorkbenchSourced(` + `MUST NOT 出现 Number.isFinite / wbS > 0`）——没有走"改成恒真/删掉"的捷径。catalog 探针的 `BASELINE_STATS_SHA256` 与本任务目标直接冲突，已换成**行为等价守卫**（**未**靠更新哈希放行）。maker 自查修掉一个真问题：一度改 E1 场景名 ⇒ `tests/` wrapper 逐字钉死场景名，红；**场景名是被 wrapper 钉死的稳定锚点，改名会让"删一段换全绿"的守卫失效**。
- **PR #105**（改 `static/`）：降级状态与本次调用绑定（`newDegradedReceipt()` 回执盒），消掉一个**可实际触发**的串味：`showView` 的 `resolveDeck()` 失败晚于详情成功返回、但在详情快照前写标志 ⇒ 详情拿到成功 deck 却显示「deck 降级」。修法不违反四条硬约束（`resolveDeck` 仍是 `async function`、返回形状不变、调用次数不变——同源探针计数桩 showView 后 1 次/详情后累计 2 次仍绿）。
- **PR #106**：`tests/` 有 **29 处** `shutil.which("node")` skip ⇒ CI 上 node 缺失会**全绿而 27 个探针根本没跑**（比红更坏）。在根 `conftest.py` 用 `pytest_sessionstart` 一处解决（选它因为在收集与 wrapper skip 之前）；只把 CI 必需的 node 升级为 fail，**MUST NOT** 做"CI 零 skip"全局禁令（会误伤 Windows 专用/env 覆盖/构建产物/bash 不可用等合理 skip），非 CI 仍 skip。
- **PR #107**：探针 `--json` 契约**冻结**（非统一）。逐个**实跑**判定 5 种形态（标准 4 / 三键超集 3 / `fail` 4 / 扁平带 `ok` 14 / 扁平无 `ok` 2），23 条登记进 `LEGACY_NONSTANDARD` 并加"清单长度 MUST NOT 增长"守卫。两个关键自证：①**判的是实跑输出不是源码文本**（只改注释 ⇒ 绿；改输出结构 ⇒ 红）；②常量刻意放**非 `test_*.py`** 文件，规避 corpus 污染——若把 23 个真实探针名写进 `test_*.py`，光"提到名字"就会让它们被判成"已接线"（上一轮 `probe_runner.py` docstring 踩过的"文档即证据"哑雷）。
- **防漏接线守卫本轮第三次当场抓出漏接线**：PR #105 新建探针但无 wrapper，守卫立刻顶出；补 wrapper 后转 5 passed。
⚠️ 编排者本轮两处任务书错误（均被 maker 正确停下上报，未硬凑）：①给 Task 2 的门禁清单写了 `tests/test_localhost_guard.py`，但那是 Task 1 在**另一分支**新建、尚未合入 master 的文件 ⇒ 退出码 4；②给 Task 3 的门禁写"diff MUST NOT 出现 `tests/`"，与其新建探针被守卫要求 wrapper **自相矛盾**。教训：任务书里引用测试文件前 MUST 确认它已在 base 上存在；门禁约束之间要自查是否互斥。
**Fog 1 裁决（用户：内网可信）**：LAN 未鉴权写端点**维持现状，不加固**。裁决依据已存档：暴露面 28 个（🔴6 / 🟡11 / 🟢11），但**不可逆毁数据能力全在闸内**（所有 DELETE、备份导出与**清库式还原**、`POST /api/settings` 改写 API Key 与网关、`wb/state/key`）；覆盖最大的 `PUT /wb/state` 由 **128-bit `X-WB-Key`** 保护且该 key **无法经 HTTP 从 LAN 取得**（`GET /wb/state/key` 挂本机闸，手机端注定 403，前端已按宿主/远端二态兼容）。**关键确定结论：加固不会断手机同步**——手机端 32 处 `/api/` 调用只写 3 个端点（`PUT /wb/state`、`POST /wb/rtc/signal`、`/wb/sync/store|fetch`），全是 `X-WB-Key` 路径，**A1–A23 无一被手机端调用**。已知代价：LAN 第二台设备从"可读可写"降级为"可读但保存按钮 403"（卡片复习打分/标掌握/存词、作文保存与版本、阅读器存词批注、模考交卷落盘、听力与长难句记录）。`GET /api/settings` 未挂闸会泄露模型网关地址与模型名（key 是掩码）——用户已知悉未单独处置。**本决策记入本 log 与计划文件 Fog 1，不另开 ADR**（如日后要正式化安全 posture，再写 `docs/adr/`）。

