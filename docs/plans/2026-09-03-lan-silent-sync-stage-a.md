# 局域网静默同步 · Stage A（配对密钥 + HTTP 轮询）实施计划

> **Goal**: 让手机（浏览器经 LAN IP 访问 + Android APP WebView）在一次输入 `host + 同步密钥` 配对后，对桌面 server 的 wb 镜像做**静默双向**自动同步（沿用 F3 `wbsync` 5s 轮询 + `applyMerge`）。
> **Tech Stack**: Python 3.11 / FastAPI（server.py）/ 原生 ES Modules `static/german/workbench.html` / node:vm 行为探针。
> **Spec Reference**: `docs/specs/2026-09-03-lan-silent-sync-design.md`（§3.4/§3.5 路线 A）；ADR-0003；`DELECTOR-DEV-RULES §2.1 本地优先与离线首选`。
> **Global Constraints**:
> - 测试用 `export PYTHONIOENCODING=utf-8; pytest <file> -k <expr> -v`；JSON `ensure_ascii=False`。
> - 本仓库**无写码子代理**（vault-exec 若派工需降级为主线程直写 + 每 Task 原子提交）。
> - workbench.html 新增逻辑**用具名函数**，不用 async IIFE；新增 HTML 的 id 不得与既有字符串测试的定位记号冲突（见 `.codebuddy/memory/MEMORY.md`）。
> - 服务端 `_require_localhost` 闸只属于**备份/敏感设置端点**，本 Stage 不得放开；wb 镜像只读 GET 保持对局域网开放、写 PUT 保持 `X-WB-Key` 鉴权。
> - 同步密钥/配对信息**不进 Git**（Zero-Leakage），只落 localStorage / `app_settings`。
> - 每个 Task：RED → 验红 → GREEN → 验绿 → REFACTOR(守卫子句) → `git commit`。提交信息 `feat(workbench): 中文` 格式。

---

### Task 1: 服务端 CORS（wb 同步端点，私有/回环 origin 反射） [Role: TDD Builder]

**Files:**
- Modify: `server.py`（`/api/wb/state` 端点区附近，~L1417-1445 之前或之后）
- Test: `test_server.py`（新增 CORS 组）

**Interfaces:**
- Consumes: `request.headers.get("Origin")`、`request.method`、`request.url.path`
- Produces: 对 `{GET,PUT} /api/wb/state` 与 `/api/wb/state/key` 在私有/回环 Origin 下回 `Access-Control-Allow-Origin: <origin>`；对 `OPTIONS` 预检返回 200 + allow 头；公共 Origin（如 `https://evil.example`）不加 ACAO 且预检 403；无 Origin 头（本机/同源/TestClient 旧用例）行为**完全不变**。

**实现要点**：
- 私有/回环 host 判定函数 `_is_private_origin(origin)`：解析 Origin 的 host，命中 `localhost` / `127.0.0.1` / `::1` / `10.*` / `172.16-31.*` / `192.168.*` 返回 True。
- 用 `@app.middleware("http")`，仅当 `request.url.path` ∈ wb 同步集 **且** 有 `Origin` **且** 私有/回环时注入头；`OPTIONS` 时短路返回 200（不落入业务路由）。无 Origin 的既有流量零影响（保护 200+ 存量测试）。

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 1: 服务端 CORS for wb sync endpoints.
> Goal: `/api/wb/state` 系端点对私有/回环 Origin 反射 ACAO 并支持 OPTIONS 预检；公共 Origin 拒绝；无 Origin 流量不变。
> Target Files: Modify `server.py`（新增 `_is_private_origin` + `@app.middleware("http")`，仅作用于 wb 同步路径集），Test `test_server.py`。
> TDD Steps:
> 1. Write failing tests (RED)：① lan_client 带 `Origin: http://127.0.0.1:8000` 请求 `GET /api/wb/state` → 200 且 `access-control-allow-origin` == 该 origin；② 同 origin `OPTIONS /api/wb/state`（模拟 PUT 预检）→ 200 且含 `access-control-allow-methods`/`-allow-headers`/`-allow-origin`；③ `Origin: https://evil.example` 的 GET 无 ACAO、OPTIONS 403；④ **无 Origin 的存量 `lan_client.put`（不带 X-WB-Key → 403）与 `client`（带 key → 200）行为不变**。
> 2. Run `python -m pytest -q test_server.py -k 'wb_state or cors or sync_sdp'` 验证失败。
> 3. Implement minimal middleware + helper (GREEN)，守卫子句压平（≤2 层）。
> 4. Run full `pytest test_server.py -q` 验证全绿（重点：无 Origin 流量回归）。
> Return: Summary with test execution evidence（RED 输出 + GREEN 通过数）。"

**Step Breakdown:**
- [ ] Step 1: 写失败测试（RED）
- [ ] Step 2: 定向跑测试验证失败信息符合预期
- [ ] Step 3: 实现最小中间件（GREEN）
- [ ] Step 4: 全量 test_server.py 回归绿
- [ ] Step 5: 守卫子句重构
- [ ] Step 6: git commit（`feat(server): wb 同步端点支持局域网 CORS（私有/回环 origin 反射）`）

---

### Task 2: 服务端 `GET /api/wb/lan-info`（局域网可读、无敏感信息） [Role: TDD Builder]

**Files:**
- Modify: `server.py`（wb_state 区，Task 1 后）
- Test: `test_server.py`

**Interfaces:**
- Consumes: `socket` 探测本机私有 IPv4
- Produces: `GET /api/wb/lan-info` → `{"hostname": str, "port": 8000, "instance_id": str, "lan_ip": str|""}`；对局域网开放（不 `_require_localhost`）。

**实现要点**：
- `lan_ip`：`socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)` 里筛私有段（`192.168.*` / `10.*` / `172.16-31.*`），取第一个；探测不到返回 `""`（UI 退化为手填）。绝不含 `X-WB-Key` 等机密。
- 复用 `routes_sync.py` 的 `_SYNC_INSTANCE_ID` 语义——本端点放 server.py，直接读同值或返回简单字符串即可（避免跨模块耦合；返回 `getattr(routes_sync, "_SYNC_INSTANCE_ID", "")` 若已 import）。

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 2: `GET /api/wb/lan-info`.
> Goal: 局域网设备可读取桌面 server 的非敏感主机信息（hostname/port/lan_ip/instance_id），供配对 UI 提示「把 IP 填进手机」。
> Target Files: Modify `server.py`, Test `test_server.py`.
> TDD Steps:
> 1. RED：`lan_client.get('/api/wb/lan-info')` → 200 且 JSON 含 `port==8000`、`instance_id` 非空；`lan_client.get('/api/wb/state/key')` 仍 403（本地闸不破）。
> 2. Run 定向 pytest 验红。
> 3. GREEN：实现端点。
> 4. 回归全绿 + 守卫子句。
> Return: Summary + 测试证据。"

**Step Breakdown:**
- [ ] Step 1: RED
- [ ] Step 2: 验红
- [ ] Step 3: GREEN
- [ ] Step 4: 回归
- [ ] Step 5: commit（`feat(server): GET /api/wb/lan-info 局域网主机信息`）

---

### Task 3: 前端 wbsync 配对模式（远端绝对地址 + 密钥推送） [Role: TDD Builder]

**Files:**
- Modify: `static/german/workbench.html`（`K` 常量 ~L955、`wbsync` IIFE ~L1066-1146、启动段 `init()` ~L3639）
- Test: `tools/wb_pair_push_probe.mjs`（新建，node:vm 行为探针，仿 `tools/wb_phone_pull_probe.mjs`）

**Interfaces:**
- Consumes: `localStorage["wb.pair.v1"] = JSON {host, key, ts}`；`K.pair`
- Produces: wbsync 暴露 `pairInfo()`；boot/push/pull 在已配对时指向 `http://{host}/api/wb/state` 且 PUT 带 `X-WB-Key: pair.key`

**实现要点**：
- `K` 增加 `pair: "wb.pair.v1"`。
- `wbsync` 内部：新增 `let _pair = null`；`loadPair()` 从 localStorage 读；`boot()` 顺序改为 ① 读配对记录（有 → `_endpoint = "http://" + _pair.host + "/api/wb/state"`、`_key = _pair.key`、置 enabled、跳本机 key 获取）；② 无配对 → 维持现逻辑（本机 `/key` 或仅拉取）。`pushNow()/pull()` 的 `fetch(ENDPOINT,…)` 全部改用 `_endpoint`（含 cache:"no-store"）。`_endpoint` 兜底为相对 `/api/wb/state`（现有行为不变）。
- 暴露 `pair: { set(host,key), clear(), info() }` 供 UI 调用；配对改动后立即 `pushNow()` 一次验证连通。
- 静默与去抖、visibilitychange/beforeunload、稳定 diff（`stable()`）、`applyMerge(remote,{silent:true})` 逻辑**全部复用不改**。

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 3: wbsync 配对远端模式。
> Goal: localStorage 存在 `wb.pair.v1` 时，wbsync 的 pull/push 指向 `http://{host}/api/wb/state`，PUT 携带 `X-WB-Key`；无配对时行为与现在逐字节一致。
> Target Files: Modify `static/german/workbench.html`, Create probe `tools/wb_pair_push_probe.mjs`.
> TDD Steps:
> 1. RED：写 `tools/wb_pair_push_probe.mjs`（仿 wb_phone_pull_probe.mjs 把真实 wbsync 源码切进 node:vm；桩 fetch 记录 (url, method, headers)；预置 `wb.pair.v1={host:'192.168.1.103',key:'k'.repeat(32)}`；调 `wbsync.push()` 后断言：PUT url 为 `http://192.168.1.103/api/wb/state`、`X-WB-Key` 头正确；再桩 GET 返回含对端卡的 payload → 断言静默合并进本地且无 toast 调用）。Run 验红。
> 2. GREEN：实现 K.pair + loadPair + boot/push/pull 改造 + `pair.set/clear/info`。
> 3. **变异验证**：把 pushNow 的 fetch 目标改回相对 `ENDPOINT` → probe 必须退出码 1（红）；恢复 → 绿。这是「远端推送真的走绝对地址」的防死测钉契约。
> 4. 跑既有 `test_german_workbench.py -q` 确保字符串切片断言不破（新增代码不要命中其定位记号）。
> Return: Summary + probe 通过/变异失败证据。"

**Step Breakdown:**
- [ ] Step 1: RED（probe 断言远端 URL + key 头）
- [ ] Step 2: 验红
- [ ] Step 3: GREEN（wbsync 配对改造）
- [ ] Step 4: 变异验证（退回相对地址必红）
- [ ] Step 5: 既有前端测试回归
- [ ] Step 6: commit（`feat(workbench): wbsync 支持局域网配对远端（host+key 静默双向）`）

---

### Task 4: 前端配对 UI（LAN 同步面板内嵌「镜像配对」小节） [Role: TDD Builder]

**Files:**
- Modify: `static/german/workbench.html`（F5 LAN 面板 ~L659-690 附近追加小节；F5 JS 区 ~L3035 后追加处理器）
- Test: `test_german_workbench.py`（新增 1-2 条存在性/契约锚定）+ `test_frontend_module_graph.py`（若该文件校验元素引用，同步注册新 id）

**Interfaces:**
- Consumes: `wbsync.pair.set/clear/info`、`GET /api/wb/lan-info`、`GET /api/wb/state/key`
- Produces: 面板根据「能否取到本机 key」二态渲染：宿主态（显示 key + lan-info 提示「把这两项填到手机」+ 复制按钮）；远端态（`host` + `key` 输入 + `保存配对` + `清除配对` + 状态行）

**实现要点**：
- 具名函数 `initLanPairPanel()`，启动（boot 后）调用；避免 async IIFE。
- 宿主判定：`fetch("/api/wb/state/key")` 成功 → 宿主态（填 key + 调 `/lan-info` 显示 ip:port）；403/失败 → 远端态（读 `wbsync.pair.info()` 回填输入框）。
- `保存配对` → `wbsync.pair.set(host, key)`；`清除配对` → `wbsync.pair.clear()`；toast 提示成功/失败（fetch 目标不通时提示「电脑未开机或 IP 不对」）。
- 不引入新弹层/阻断式 modal（遵守 FRONTEND-DESIGN-PATTERNS，用行内 hint）。

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 4: 局域网镜像配对 UI.
> Goal: 设置页 LAN 同步面板下新增小节，宿主显示密钥+IP 供复制，远端输入 host+key 保存/清除，全部走具名函数、不弹阻断 modal。
> Target Files: Modify `static/german/workbench.html`, Test `test_german_workbench.py`.
> TDD Steps:
> 1. RED：写存在性锚定（新 id `wbPairHostIn`/`wbPairKeyIn`/`btnPairSave`/`btnPairClear` 与函数名 `initLanPairPanel` 出现）——注意不破坏既有 split 定位记号（先查该文件用哪些特征串定位，新 HTML 放旧锚之后）。
> 2. GREEN：实现面板 + JS 处理器。
> 3. 回归 `test_german_workbench.py -q` 全绿。
> Return: Summary + 测试证据 + 手动验证说明。"

**Step Breakdown:**
- [ ] Step 1: RED（锚定测试）
- [ ] Step 2: 验红
- [ ] Step 3: GREEN（UI + 处理器）
- [ ] Step 4: 前端全量回归
- [ ] Step 5: commit（`feat(workbench): 局域网镜像配对面板（宿主/远端二态）`）

---

### Task 5: 集成回归 + 文档回填 + 真机验证清单 [Role: TDD Builder]

**Files:**
- Modify: `AGENTS.md`、`FEATURES.md`、`docs/specs/2026-09-03-lan-silent-sync-design.md`（§6 勾选 Stage A）
- Test: 全量 `pytest test_server.py` + `pytest test_german_workbench.py` + `pytest test_frontend_module_graph.py`（定向子集 + 真实服务冒烟，遵守 `.codebuddy/memory` 中「safe-delete 守卫 / 命令过长」经验）

**Subagent Prompt Scaffold (for /vault-exec):**
> "Implement Task 5: Stage A 集成回归与回填.
> Goal: 三个测试文件定向全绿；AGENTS.md/FEATURES.md 补「局域网镜像配对同步」条目；spec §6 Stage A 勾选；输出真机手动验证清单（桌面浏览器↔手机浏览器 / 桌面↔Android APP 前台 两条路径的 pairing→push→pull→双向静默用例）。
> TDD Steps:
> 1. 跑回归（定向子集），全绿。
> 2. 文档回填（AGENTS.md 架构段、FEATURES.md 功能表、spec 进度）。
> 3. 冒烟：本环境起真实 server，用 curl 带 Origin 头验 ACAO 与预检、`lan-info` 字段、未配对 403。
> Return: 回归证据 + 冒烟输出 + 真机清单。"

**Step Breakdown:**
- [ ] Step 1: 定向全量回归
- [ ] Step 2: 真实服务 CORS/预检/lan-info 冒烟
- [ ] Step 3: 文档回填
- [ ] Step 4: 真机手动验证清单产出
- [ ] Step 5: commit（`docs: Stage A 局域网配对同步回归与回填`）

---

## Stage A 手动验证清单（交付物）
1. 桌面浏览器开 `/api/wb/state/key` 可达 → 配对面板显示宿主态（密钥 + 192.168.x.x:8000）。
2. 手机浏览器输入 `http://<桌面IP>:8000` → 设置 → LAN 同步 → 远端态输入 host+key → 保存 → 手机背 3 词 → 桌面（任一端刷新）看到进度；反向桌面背 → 手机 5s 内静默合并、无 toast。
3. Android APP（前台）同 2：APP 内配对后与桌面双向静默同步。
4. 桌面关机 → 手机正常学习、无报错；桌面重开 → 恢复自动对账。
5. 清配对 → 推送 403、拉取仍可（只读镜像不破）。

## Stage B（后续独立计划，本文件不含）
自动化 WebRTC（持久配对凭证替代手动码、自动建连/重连、DataChannel 双向、信令端点 `X-WB-Key` 鉴权）——待 Stage A 真机验证通过后单独出 `2026-09-03-lan-silent-sync-stage-b.md`。
