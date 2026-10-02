# WiFi 内容分发：手机拉取式卡包导入（遇见区）Implementation Plan

> **Goal**: 让真实用户在手机上无需发版即可获得新内容——桌面（job#1 产包落库）作为局域网"货架"，手机遇见区新增「从电脑导入」：手机服务端出站拉取桌面卡包并幂等落库。
> **Tech Stack**: Python 3.11 + FastAPI（双实例语义：桌面货架 / 手机拉取）/ 既有 `httpx` 出站 / 原生 ES 前端 / pytest 双 TestClient
> **Spec Reference**: ADR-0004（LAN 同步"拉取免 key、推送要 key"纪律）/ ADR-0010（遇见区）/ `start.py:36-42`（Android 绑回环的安全决策）
> **Global Constraints**:
> - **方向反转（手机拉，非桌面推）是硬约束下的唯一正确架构**：`start.py` 中 Android 实例**有意绑 `127.0.0.1`**（绑 0.0.0.0 会把无鉴权 `POST /api/settings` 暴露给局域网——既有安全红线，不可推翻）；桌面绑 `0.0.0.0` 天然是货架。
> - 手机 `pull-pack` 挂 `_require_localhost`（红线 7）；桌面货架**只读、局域网开放**（与 `GET /api/wb/state` 同级的"拉取免 key"纪律），**绝不提供写操作**。
> - 前端只调**本机** API（同源零跨域）；出站拉取由手机服务端完成（出站不受监听绑定限制）。
> - Go 侧零改动（`runner.go:54` `DeliverURL` 投递已就绪）；Android 打包面零改动（无新模块）。
> - `ruff check .` 零告警；全量 pytest 基线 719+1 不回退；分支 `feature/wifi-content-pull`，CPE 实现 + 主线程提交，PR CI 真验证。

---

### 架构与数据流

```
桌面：delector job run encounter-pack --deliver-to http://127.0.0.1:8000
      → 既有 import-pack 落库（pack_json 完整保留）
      → GET /api/encounter/packs            （货架清单，局域网只读）
      → GET /api/encounter/packs/{pack_id}   （完整 encounter-pack/v1）

手机：遇见区 UI「从电脑导入」→ POST /api/encounter/pull-pack（localhost 闸）
      → 手机服务端 httpx 出站 GET 桌面货架 → validate_pack → import_encounter_pack（pack_id 幂等）
      → 遇见区列表立即可读
```

### Task 1: 桌面货架端点 [TDD Builder]
**Files**: Modify `delector/routes/encounter.py`；Test `tests/test_encounter_pull.py`
**要点**:
- `GET /api/encounter/packs`：列货架（`pack_id / title / level / 摘要`），空表返回空清单；**不返回任何机密字段**。
- `GET /api/encounter/packs/{pack_id}`：返回完整 `encounter-pack/v1`（从 `pack_json` 反序列化）；未知 `pack_id` → 404。
- 不挂 localhost 闸（局域网只读内容数据）。
**测试**: TestClient 全链路——建 2 篇 → 列表含两包且字段完整、无 `pack_json` 外泄字段断言；单包 GET 过 `validate_pack`；未知 id 404；空表 200 空清单。

### Task 2: 手机拉取端点 [TDD Builder]
**Files**: Modify `delector/routes/encounter.py`；Test 同 T1 文件
**要点**:
- `POST /api/encounter/pull-pack`（**挂 `_require_localhost`**）：入参 `{desktop_base, pack_id?}`。
  - `pack_id` 省略 → 代理货架清单（前端零跨域）；
  - 带 `pack_id` → `httpx.get(f"{desktop_base}/api/encounter/packs/{pack_id}", timeout≈5s)` → `validate_pack` → `import_encounter_pack`（幂等）→ 返回导入结果。
- 出站失败人话化：连不上 → 「检查电脑是否开着 DeLector、是否同一 WiFi / 防火墙」。
- `desktop_base` 校验：必须是 `http(s)://` 前缀的合法 URL（防 SSRF 式注入——虽然是本机闸内操作，仍做基础校验，复用既有 security 思路可简化）。
**测试**: 双 TestClient（`app_shelf` 桌面 + `app_phone` 手机，各自独立 tmp 库）+ monkeypatch 出站 httpx 调用到 shelf 的 TestClient（不真开端口、不引依赖）；断言：拉取落库后手机列表可见、**重复拉取不增行（幂等）**、`pull-pack` 无 localhost 来源 → 403、连不上 → 人话错误信息、`validate_pack` 拒绝不合法 pack。

### Task 3: 前端「从电脑导入」[Builder + 探针]
**Files**: Modify `static/js/encounter.js`（+ 必要的 CSS 复用既有类）
**要点**:
- 列表页加「从电脑导入」入口（样式与现有「添加短文」入口一致）。
- 流程：输入桌面地址（`http://192.168.x.x:8000`，`localStorage` 记忆键 `enc.desktop.v1`）→ 列货架 → 选包导入 → 刷新列表；空货架/连不上显示人话提示（含「在电脑端 背词同步 面板可查看本机 IP」引导）。
- 导入中禁用按钮 + 完成后 notify（复用既有 toast）。
**测试**: 静态/行为探针——入口存在、记忆键常量、**断言前端只调本机 `/api/encounter/pull-pack` 而非直连桌面**（跨域安全，红线 11 精神）。

### Task 4: 收官 [Verifier]
**Files**: Modify `WORKMEMORY/PROJECT_OVERVIEW.md`、`WORKMEMORY/work.log`；Create 本文件已在 T0
**要点**: README（FEATURES）补一小节作者流程（桌面跑 job#1 --deliver → 手机点导入）；全量门禁（pytest 719+1 不回退、`ruff check .` 零告警、Go 门禁不受影响）；开 PR 合 master（PR CI 真验证）。

---

## 执行状态（收官时回填）

- 状态：**PENDING**
- 手工冒烟（作者一次性，发版前）：
  1. 桌面：`delector job run encounter-pack --corpus-dir <语料> --deliver-to http://127.0.0.1:8000`
  2. 手机：遇见区 →「从电脑导入」→ 填桌面 IP → 选包 → 列表出现新短文。
- 已知边界：不做 mDNS 自动发现（YAGNI，手填 + 记忆 + `lan-info` 引导）；不搬运 WebRTC（HTTP 拉取已满足）。
