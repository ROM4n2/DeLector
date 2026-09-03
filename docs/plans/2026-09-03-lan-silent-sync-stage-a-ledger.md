# Vault-Exec Ledger — 局域网静默同步 Stage A

> **计划**：`docs/plans/2026-09-03-lan-silent-sync-stage-a.md`
> **Spec**：`docs/specs/2026-09-03-lan-silent-sync-design.md`
> **执行模式（降级，如实注明）**：本环境**无写码子代理**（`task` 仅只读 code-explorer），
> vault-exec 的 multi-subagent 派工在此降级为「编排者主线程直写 + TDD 纪律 + Maker-Checker
> 由主线程自查（对照 01-Rules 与计划验收）+ 每 Task 原子提交」。逐条执行计划中的 RED→GREEN→commit。
> **初始化日期**：2026-09-03

## 任务状态

| Task | 标题 | 状态 | 提交 | 证据 |
|---|---|---|---|---|
| Task 1 | server CORS（wb 同步端点私有/回环 origin 反射） | ✅ 完成 | `9b0a95b` | RED 4 失败→GREEN 13 通过；全量 test_server.py 210 passed |
| Task 2 | GET /api/wb/lan-info | ✅ 完成 | `f344739` | RED 404→GREEN 15 通过（定向 wb_state/cors/lan_info）；全量 test_server.py 210 passed |
| Task 3 | 前端 wbsync 配对远端模式 | ✅ 完成 | `5dd68a5` | 探针 `tools/wb_pair_push_probe.mjs` RED（无配对 key 请求/缺远端绝对地址）→GREEN；变异验证（pushNow 退回相对 ENDPOINT）探针退出码 1 → 恢复绿；test_german_workbench.py 77 passed |
| Task 4 | 前端配对 UI 二态渲染 | ✅ 完成 | `b9a01c2` | RED 锚定 2 failed（缺 wbPair* id / initLanPairPanel）→GREEN 2 passed；内联脚本 `node --check` SYNTAX-OK；test_german_workbench + test_frontend_module_graph 87 passed；4 支 node:vm 探针全绿 |
| Task 1 补漏 | wb CORS 公共 Origin 预检显式 403 | ✅ 完成 | `c3d67ef` | Task 5 冒烟发现公共 Origin 的 OPTIONS 预检落 405（仅靠无 ACAO 兜底），与任务书「预检 403」契约不符；中间件改为对公共/未知 Origin 显式 403，测试断言由宽到严（==403 且无 ACAO）；定向 wb/cors 回归 15 passed |
| Task 5 | 集成回归 + 文档回填 + 冒烟 | ✅ 完成 | `604bfab`（docs，本 ledger 另行提交） | server wb/cors 定向 15 passed；workbench+module_graph 87 passed；TestClient 全链路冒烟 18 项 SMOKE ALL PASS；AGENTS.md/FEATURES.md/spec §6 回填（详见文末 Task 5 节） |

## Maker-Checker 自查记录（降级替代 reviewer subagent）

- 每 Task 完成后：对照计划验收点 + `AGENTS.md`/相关 `01-Rules`（本仓库以内存中的
  DELECTOR-DEV-RULES / CODING-UNIVERSAL 约束为准）逐条复核差异，再提交。

### Task 3 自查（checker：主线程，对照计划验收点）

- 计划 Interface Produces（wbsync 暴露配对信息、已配对 push/pull 指绝对地址、PUT 带配对 key）✅ 实测：
  boot 有配对 → 不发本机 `/key`、直接 GET `http://<host>/api/wb/state`；`pushNow()` PUT 绝对地址 + `X-WB-Key`。
- 计划 Step 6 变异验证 ✅ 已执行：把 `pushNow()` 的 fetch 目标改回相对 `ENDPOINT` → 探针退出码 1；恢复后探针绿。
- 计划约束「静默/去抖/稳定 diff/applyMerge silent 复用不改」✅：本次未触碰 `push()/pull() 内 stable diff 与
  `applyMerge(remote,{silent:true})`、visibilitychange/beforeunload、轮询定时器；逐字节对比 commit diff 确认。
- 计划约束「无配对行为与现状一致」✅：未配对走原 boot 分支（本机 `/key` → 拿不到仅拉取）；既有三支
  wbsync node:vm 探针（`wb_sync_probe`/`wb_phone_pull_probe`/`wb_phone_pull_silent_probe`）+ phone-pull/silent
  契约测试全绿，证明既有路径未回归。
- workbench.html 字符串定位记号（`(async () => {`、`loadAll();`、`})();` 等）未被新增代码命中 ✅ 77 项解析测试全绿。
- 密钥/配对仅落 localStorage、不进 Git ✅（`K.pair="wb.pair.v1"`，无日志/无远端上报）。

---

## Task 5 冒烟与自查（checker：主线程）

### 冒烟方式（如实注明约束）
计划要求「起真实 server 用 curl 带 Origin 头验证」，本环境起后台进程 / 含 `rm` 的命令会触发
审批守卫且超时无批准，故降级为 **TestClient 全链路冒烟**（一次性脚本 `tools/_stage_a_smoke_check.py`，
同一 ASGI app + 中间件 + 路由，构造与单元测试一致的回环 / 局域网双客户端；脚本已用后即删）。
输出 **SMOKE ALL PASS**（18 项）：
lan-info 200 且字段齐全、无 key/secret 泄漏；本机 `/key` 幂等可取、局域网 403；回环 Origin 与
私有 Origin 的 GET 均反射 ACAO；私有 Origin PUT 预检 200 且 allow-methods 含 PUT、allow-headers 含
X-WB-Key、ACAO 反射；公共 Origin 预检 403 且无 ACAO、GET 200 但无 ACAO；未配对 PUT 403、
带 key PUT 200、写后本机回读 payload 一致。
真实网卡层（桌面↔手机）的验证见文末「真机手动验证清单」。

### 回归补漏（冒烟发现，`c3d67ef`）
公共 Origin 的 `OPTIONS /api/wb/state` 原实现落到「无 OPTIONS 路由 → 405」，仅靠「无 ACAO」兜底，
与任务书「预检 403」契约不符。已把中间件改为：wb 路径 + 有 Origin 的 `OPTIONS` 请求，对公共/未知
Origin 显式 `Response(403)`（无 ACAO）；测试断言从「!=200 或无 ACAO」收紧为「==403 且无 ACAO」。

### 回归证据
- `python -m pytest -q test_server.py -k "wb or cors"` → **15 passed, 197 deselected**。
- `python -m pytest -q test_german_workbench.py test_frontend_module_graph.py` → **87 passed**。
- `pyflakes` / lint 对 server.py、test_server.py **0 告警**。

### Task 5 自查
- 计划 Step 3 文档回填 ✅：AGENTS.md（快照时间、HEAD 注记、路由清单新增 4 条 wb 端点 +
  「局域网静默同步（镜像配对 · Stage A）」小节）；FEATURES.md（§十三 表新增「镜像静默同步 Stage A」行）；
  spec §6 Stage A 勾选 + 状态行注明「A 已落地 2026-09-03、信令端点 X-WB-Key 鉴权归 B」。
- 密钥 / 配对信息不进 Git ✅；`GET /key` 保留 `_require_localhost`、`GET /api/wb/state` 拉取免 key 不变 ✅。
- 交付物「真机手动验证清单」见下（也收录在计划文件文末）。

## Stage A 真机手动验证清单（交付物；2026-09-03 首次执行，部分通过）

> 执行日期：2026-09-03。✅ = 通过；🟡 = 部分/暂无法执行（注明原因）；⬜ = 未执行。

1. ✅ 桌面浏览器 → 背词工作台 → 设置 → LAN 同步 →「镜像配对」显示**宿主态**：32 位密钥 +
   `http://192.168.x.x:8000`（由 `GET /api/wb/lan-info` 回填）。
2. ✅ 手机浏览器访问 `http://<桌面IP>:8000` → 同面板**远端态**：填 `host + key` → 保存 →
   手机背 3 词 → 桌面任一端刷新可见（用户实测「看到认识率变化」）；桌面背 1 词 → 手机 5s 内
   静默合并（无 toast、不切视图）。**手机 → 桌面 与 桌面 → 手机 浏览器两条路径均通过**。
3. 🟡 Android APP（前台）重复第 2 步：APP 独立实例与桌面**对等**双向静默同步。
   用户说明：**手头 APP 还是旧版（未内嵌本 Stage A 代码），暂无法测试**。
   前置：APP 端需随下次发版（重新打包内嵌新 server + workbench 前端）后才可验证。
4. ⬜ 桌面关机 → 手机学习正常、无报错；桌面重开 → 恢复自动对账。
5. ⬜ 清除配对 → 手机推送 403、拉取仍 200（只读镜像不破）；公网恶意站点跨域请求被浏览器拦截。

**结论**：Stage A 核心路径（配对面板 + 双端浏览器静默双向对账）真机可用；APP 项与韧性项（4/5）
待 APP 发版后补测。据此，Stage B（自动化 WebRTC）立项门槛（Stage A 真机验证通过）**暂不视为已达成**，
建议在 APP 版验证完成后再单独立项。
