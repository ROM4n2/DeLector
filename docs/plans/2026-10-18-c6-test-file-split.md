# C6 实施计划：测试文件按被测面切分（`test_server.py` / `test_desktop_shell.py`）

> **Goal**: 把两个巨型测试文件按**被测面**切成多个小文件，只搬归属、不改用例语义；并先把它们文件内部定义的共享 fixture / helper 提取成显式共享层，使搬迁不依赖隐式同文件可见性。
> **Tech Stack**: Python 3.11 / pytest（无新插件，零新依赖）
> **Spec Reference**:
> - `docs/reviews/2026-10-16-open-items-backlog.md`（C6 行；**本计划已把 `test_german_workbench.py` 移出 C6 范围** —— 该文件划归 C7 独占，见下）
> - `docs/README.md`（plans 放置约定）
> **Global Constraints**:
> - **只搬归属、不改用例语义（MUST）**：断言、用例名、参数化取值一律逐字不变。搬迁中若发现某用例确实依赖**同文件执行顺序或模块级可变状态**，MUST 停下来登记并把该依赖显式化，不得用「顺手改成独立」来掩盖。
> - **用例数守恒（MUST）**：搬迁前后 `pytest --collect-only -q` 的**收集总数必须完全相等**，且全量套件的通过数不得下降。
> - **零新依赖**：不引入 `pytest-xdist` / `pytest-randomly` / `pytest-order`。
> - **文件契约**：UTF-8 CRLF（0 lone LF）；`mypy --follow-imports=skip tests` 零错误；`ruff check .` 零告警。
> - **并行占面（MUST）**：本工作流**只**动 `tests/test_server*.py`、`tests/test_desktop_shell*.py`、`tests/server_helpers.py`（新增）、`tests/conftest.py`。**禁触** C7 独占面（`static/german/workbench.html` · `static/js/**` · `static/css/**` · `tools/wb_*.mjs` · 两个 build 工具 · `tests/test_german_workbench.py` 及 C7 其余探针文件）与 C8 面（`delector/**` · `.github/**` · `.gitignore`）。
> **Branch**: `refactor/c6-test-file-split` —— 从 `master` 切出，全套门禁全绿后提 PR 合入，严禁直推 `master`。

---

## 🏛️ Decisions So Far

- **范围变更（对登记的修正，实测依据）**：原 C6 行写「`test_server.py` 7271 行 / `test_german_workbench.py` 3913 / `test_desktop_shell.py` 2664」三选。**`test_german_workbench.py` 已划归 C7 独占**（它的重写正是 C7 的前置），本计划只做另两个文件。当前实测行数：`test_server.py` **7614** / `test_desktop_shell.py` **2819**（登记表里的数字已过期，勿引用）。
- **「避开 ai-polish 段」这条约束已失效**：原登记写 `test_server.py` 须避开 ai-polish 测试段（当时是在途面）。C1（PR #147）与 C3（PR #148）均已合入 master，ai-polish 面**已冻结** ⇒ 该约束**不再是理由**，切分方案不受它限制。
- **`client` fixture 住在被测文件内部（实测）**：`tests/test_server.py:62-66` 定义
  ```python
  @pytest.fixture
  def client():
      return TestClient(app, client=("127.0.0.1", 54321))
  ```
  而 `tests/conftest.py` 只有一条 session 级 autouse 的仓库根库守卫（`:38-39`）。⇒ **切分必须先提取共享层**，「纯搬文本」不可行。
- **文件命名裁决 = 扁平前缀式**：新文件采用 `tests/test_server_<domain>.py` 与 `tests/test_desktop_shell_<domain>.py`，**不建子包**。理由：本仓 `tests/` 现为全扁平布局；建 `tests/server/` 子包会引入包内 `__init__.py`/conftest 发现层次与 `mypy --follow-imports=skip tests` 的路径语义变化，收益为零。
- **切分粒度 = 按路由/被测域**，`test_server.py` 的 31 个注释分段归并成 **9 个域文件**（见 Task 2~5 的分配表），每文件目标 600~1000 行。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 共享层提取（fixture + helper 显式化） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]
*(此 Task **不搬用例**，只让共享面变成显式依赖；用例数必须逐字守恒)*

**Files:**
- Create: `tests/server_helpers.py`
- Modify: `tests/conftest.py`（迁移 `client` fixture）
- Modify: `tests/test_server.py`（改 import，删已迁出的定义）
- Modify: `tests/test_desktop_shell.py`（若它引用 `test_server` 的 helper，一并改）

**Interfaces:**
- Consumes: `from delector.server import app`；`fastapi.testclient.TestClient`
- Produces:
  - `tests/conftest.py` 新增 `client` fixture（**逐字保持** `TestClient(app, client=("127.0.0.1", 54321))` 的语义与默认作用域）
  - `tests/server_helpers.py` 承载 `test_server.py` 的模块级常量与纯 helper（如 `_stub_api_key` / `_parse_sse` / `_ScriptedChat` / `_ESSAY_TEXT` 等，以实测清单为准）

**Injected Instincts:**
- [ ] `[Instinct: Fixture-Precedence-Safe]`: `client` 下沉到 conftest 后，**其它测试模块里同名局部 fixture MUST 继续遮蔽它**（pytest 解析顺序：局部 > conftest）。改完必须全量跑一次证明无文件被动改变行为。
- [ ] `[Instinct: Explicit-Beats-Implicit]`: 禁止把 helper 用 `from test_server import *` 之类手段桥接；新文件 MUST 显式 `from tests.server_helpers import …`（或按 pytest rootdir 约定的同等显式形式）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 共享层提取（C6）.
> Mode: AFK | Role: TDD Builder
> Steps:
> 1. 先做搬前基线（两条都要，原文记录）：`python3 -m pytest tests/ --collect-only -q | tail -3`（记收集总数）与 `python3 -m pytest tests/ -q | tail -3`（记通过数）。
> 2. grep 全仓：`grep -rn 'from test_server import\\|import test_server' tests/ tools/` —— 若有外部引用，先登记再改。
> 3. 列出 `tests/test_server.py` 的模块级定义（常量 + helper + fixture），分类为「共享」与「仅本域使用」。
> 4. 把共享项迁到 `tests/server_helpers.py` 与 `tests/conftest.py`；`test_server.py` 改为显式 import。
> 5. **用例数守恒核验**：重跑 `--collect-only -q | tail -3` 与全量 `-q | tail -3`，与第 1 步逐字比对。
> 6. `ruff check` + `mypy --follow-imports=skip tests`。
> Return: 摘要 + 第 1/5 步四条命令的原文 + 迁移清单（哪些名去了哪里）+ git diff stat。"

**Step Breakdown:**
- [ ] **Step 1**: 记录搬前基线（收集总数 + 全量通过数）
- [ ] **Step 2**: grep 外部引用 `test_server` 的模块
- [ ] **Step 3**: 清点模块级定义并分类（共享 / 本域）
- [ ] **Step 4**: 建 `tests/server_helpers.py`；`client` 迁入 `conftest.py`；改 import
- [ ] **Step 5**: 用例数守恒核验（收集总数 + 全量通过数逐字相等）
- [ ] **Step 6**: ruff + mypy tests
- [ ] **Step 7**: Physical Evidence Gate + 原子提交（`refactor(tests): extract server test shared layer`）

---

### Task 2: 搬批 1 —— 基础设施域（health / 打包 / 版本 / Android 回退） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `tests/test_server_health.py` · `tests/test_server_packaging.py` · `tests/test_server_android_fallback.py`
- Modify: `tests/test_server.py`（删已搬段）

**域分配（行号为**搬前**的 `test_server.py` 分段锚点，实测）**：

| 新文件 | 来源段（搬前行号） |
| --- | --- |
| `test_server_health.py` | `6651`（`GET /api/health` 真健康端点）· `6494`（TTS 并发闸 k=4） |
| `test_server_packaging.py` | `5183`（打包三加固：`.env` 泄漏闸 / 构建指纹 / 版本 fallback）· `5364`（版本号含斜杠回归锁）· `4162`（v4.7.0 架构与数据完整性契约） |
| `test_server_android_fallback.py` | `2301`（Android/Chaquopy：spacy 缺席必须纯 Python 回退）· `3535`（Android spaCy 加载契约）· `3725`（前端错误展示，静态面） |

**Injected Instincts:**
- [ ] `[Instinct: Anchor-Moves-With-Code]`: 段内若有引用**行号**的注释或探针（如「见 `main.py:2383`」这类文档锚点），搬迁后 MUST 核对锚点仍指向真实位置。
- [ ] `[Instinct: No-Order-Coupling]`: 搬完必须能**单独**跑通（`pytest tests/test_server_health.py -q` 绿），而不是靠其它文件先跑了某段才有状态。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 搬批 1 —— 基础设施域（C6）.
> Mode: AFK | Role: TDD Builder
> Steps:
> 1. 记录搬前：`python3 -m pytest tests/ --collect-only -q | tail -3`（总数）。
> 2. 按上表把三段搬入三个新文件；每段**逐字**复制，只加新的 import 头。
> 3. 每搬一个文件后立刻单独跑它：`python3 -m pytest tests/test_server_<domain>.py -q`。
> 4. 三个都搬完后重跑 `--collect-only -q | tail -3`，与第 1 步**逐字相等**。
> 5. 跑 `python3 -m pytest tests/test_server.py -q` 确认剩余部分仍绿。
> Return: 摘要 + 收集总数前后对照 + 每个新文件的行数 + git diff stat。"

**Step Breakdown:**
- [ ] **Step 1**: 记录搬前收集总数
- [ ] **Step 2**: 逐段搬到 3 个新文件（逐字）
- [ ] **Step 3**: 每个新文件单独跑绿
- [ ] **Step 4**: 收集总数守恒核验
- [ ] **Step 5**: `test_server.py` 剩余部分仍绿
- [ ] **Step 6**: Physical Evidence Gate + 原子提交（`refactor(tests): split server infra test domains`）

---

### Task 3: 搬批 2 —— 数据域（备份/还原 · 进度/测验/FSRS · 预备包） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `tests/test_server_backup_restore.py` · `tests/test_server_progress_quiz.py` · `tests/test_server_prep.py`
- Modify: `tests/test_server.py`

| 新文件 | 来源段（搬前行号） |
| --- | --- |
| `test_server_backup_restore.py` | `758`（v3.10.0 备份往返）· `3431`/`3433`（备份源边界 prepare/download/restore）· `5767`（ADR-0016 备份列清单 + 还原后补迁移） |
| `test_server_progress_quiz.py` | `1335`（Phase A Delete & Master）· `1423`（Phase B Quiz Record）· `1481`（Phase C Progress Stats）· `1523`（FSRS + Cloze）· `1980`（形态学与可分动词引擎） |
| `test_server_prep.py` | `3799`（GET /api/prep/matrix）· `3929`（GET/POST /api/prep/saved） |

**Injected Instincts:**
- [ ] `[Instinct: Stored-Data-Contract]`: 备份/恢复段涉及**存量数据契约**（`PROJECT_OVERVIEW` 红线 12）⇒ 搬迁 MUST 让「只增 + 只补空 + 幂等」三条断言继续约束真实端点，不得因换文件而失去覆盖。
- [ ] `[Instinct: Phase-Order]`: `Phase A/B/C` 三段可能有**隐含的先后依赖**（同一 DB 状态）；若单独跑红，MUST 登记并显式化依赖，不得把它们拆散到无法复现的顺序里。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 搬批 2 —— 数据域（C6）.
> Mode: AFK | Role: TDD Builder
> Steps: 同 Task 2 的 5 步，但域分配按本 Task 的上表。
> 特别要求：若 `Phase A/B/C` 单独跑出现失败，**先停下登记**（记录失败用例名与顺序事实），不要就地改断言。
> Return: 摘要 + 收集总数前后对照 + 每个新文件行数 + 单独跑结果 + git diff stat。"

**Step Breakdown:**
- [ ] **Step 1**: 记录搬前收集总数
- [ ] **Step 2**: 逐段搬到 3 个新文件
- [ ] **Step 3**: 每个新文件单独跑绿（Phase 依赖若暴露，先登记）
- [ ] **Step 4**: 收集总数守恒核验
- [ ] **Step 5**: Physical Evidence Gate + 原子提交

---

### Task 4: 搬批 3 —— 同步/卡片域（wb 同步与 RTC · LAN · 卡片与词库） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `tests/test_server_wb_sync_rtc.py` · `tests/test_server_lan.py` · `tests/test_server_cards_vocab.py`
- Modify: `tests/test_server.py`

| 新文件 | 来源段（搬前行号） |
| --- | --- |
| `test_server_wb_sync_rtc.py` | `3967`（wb/sync/store & fetch）· `4076`（WebRTC 信令中继）· `5561`（Workbench 进度 server 同步）· `5661`（ADR-0016 Phase 3 / Task 2 镜像写入同事务） |
| `test_server_lan.py` | `5924`（局域网 CORS）· `6001`（GET /api/wb/lan-info） |
| `test_server_cards_vocab.py` | `6023`（GET /api/cards/vocab）· `6231`（exam catalog B1 注册）· `6252`（known-lemmas「已学」口径） |

**Injected Instincts:**
- [ ] `[Instinct: Sync-Idempotence]`: 同步域断言多含「幂等 / 只增」语义 ⇒ 搬迁后必须保持同一断言文本（这类语义最容易被「顺手重写」破坏）。
- [ ] `[Instinct: Index-Split-Check]`: 本批涉及 wb 镜像与统一池投影**同事务**断言（`5661`）——搬迁时必须确认事务断言仍在**同一个用例函数内**（拆成两个用例会让事务原子性失去验证）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: 搬批 3 —— 同步/卡片域（C6）. Mode: AFK | Role: TDD Builder
> Steps: 同 Task 2 的 5 步，域分配按本 Task 上表。
> 特别要求：不得把任何单个用例函数拆成两个（尤其事务/幂等类）；只做文件级搬迁。
> Return: 摘要 + 收集总数前后对照 + 每文件行数 + 单独跑结果 + git diff stat。"

**Step Breakdown:**
- [ ] **Step 1**: 记录搬前收集总数
- [ ] **Step 2**: 逐段搬到 3 个新文件
- [ ] **Step 3**: 每个新文件单独跑绿
- [ ] **Step 4**: 收集总数守恒核验
- [ ] **Step 5**: Physical Evidence Gate + 原子提交

---

### Task 5: 搬批 4 —— 安全/润色域（settings 边界 · SSRF/IPv6 · AI 润色循环） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `tests/test_server_settings_security.py` · `test_server_ai_polish.py`
- Modify: `tests/test_server.py`（本批后该文件应只剩零星段或清空）

| 新文件 | 来源段（搬前行号） |
| --- | --- |
| `test_server_settings_security.py` | `3348`（v4.4 Task1 Settings localhost-only 边界）· `2930`（SSRF 多地址校验 / 重定向逐跳预校验 / TTS 长度闸）· `2971`（IPv6 过渡格式判定）· `2859`（查词链 lemma-first / EXT 接线 / 诚实 source）· `4467`（Task 1 Hardening & Regression） |
| `test_server_ai_polish.py` | `6759`（AI 润色循环：返回契约 / 适用性闸门 / 流式进度 / 断连取消）· `6907`（Task 1/2 评审闭环：端点级接线 + 引擎降级诚实性）· `7019`（Task 7 文本族感知提示词参数化）· `3576`（AI 402 / timeout / non-JSON ⇒ 502）· `3902`（GET /api/audio/tts）· `6405-6407`（待实测归位段） |

**Injected Instincts:**
- [ ] `[Instinct: Frozen-Surface]`: AI 润色面刚由 C1/C3 冻结交付 ⇒ 本批 MUST 保持其断言**逐字不变**（含 `judge_feedback` / `text_type` / `usage` 相关断言）。
- [ ] **`⚠️ 与 C8 的短时交叠（MUST 处理）`**：C8 工作流并行修改 `tests/test_server.py` 的音频缓存/encounter/settings 三处。**本 Task 必须在 C8 合入 master 之后再开工**，否则两边同时改同一文件必冲突。若 C8 未合入，本 Task 挂起等待。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 5: 搬批 4 —— 安全/润色域（C6）. Mode: AFK | Role: TDD Builder
> **前置**：确认 `tests/test_server.py` 已包含 C8 的改动（`git log --oneline -5 -- tests/test_server.py` 里能看到 C8 的提交）后再开工；否则中止并报告。
> Steps: 同 Task 2 的 5 步，域分配按本 Task 上表；`6405-6407` 段先实读确认归属。
> Return: 摘要 + 收集总数前后对照 + `test_server.py` 剩余行数 + 单独跑结果 + git diff stat。"

**Step Breakdown:**
- [ ] **Step 0**: 前置确认 C8 已合入（否则挂起）
- [ ] **Step 1**: 记录搬前收集总数
- [ ] **Step 2**: 逐段搬到 2 个新文件
- [ ] **Step 3**: 每个新文件单独跑绿
- [ ] **Step 4**: 收集总数守恒核验
- [ ] **Step 5**: Physical Evidence Gate + 原子提交

---

### Task 6: `test_desktop_shell.py` 按被测面切分 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `tests/test_desktop_<domain>.py`（域清单**由本 Task 第 1 步实测分段后确定**）
- Modify: `tests/test_desktop_shell.py`

**Injected Instincts:**
- [ ] `[Instinct: Measure-Before-Split]`: 该文件的分段结构未实测（2819 行）⇒ 域划分 MUST 先做一次分段清点，不得凭猜测事先指定文件名。
- [ ] `[Instinct: C8-Win-Not-Lost]`: C8 的恒真断言修复落在 `:2110` ⇒ 搬迁后该断言 MUST 仍在（且已是修复后的强写法），不得搬丢或回退。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 6: `test_desktop_shell.py` 按被测面切分（C6）. Mode: AFK | Role: TDD Builder
> Steps:
> 1. 记录搬前：`python3 -m pytest tests/test_desktop_shell.py --collect-only -q | tail -3`。
> 2. 清点该文件的分段结构（注释头 / 类 / 模块级分组），提出 3~5 个域的划分并**写进 commit message**。
> 3. 逐域搬迁（逐字），每搬一个立刻单独跑绿。
> 4. 收集总数守恒核验。
> 5. 确认 C8 在 `:2110` 修好的 stdout 同一性断言仍在（在新文件里 grep 到它）。
> Return: 摘要 + 收集总数前后对照 + 域划分表 + git diff stat。"

**Step Breakdown:**
- [ ] **Step 1**: 记录搬前收集总数
- [ ] **Step 2**: 实测分段并定域划分
- [ ] **Step 3**: 逐域搬迁 + 单独跑绿
- [ ] **Step 4**: 收集总数守恒核验
- [ ] **Step 5**: C8 修复未丢核验
- [ ] **Step 6**: Physical Evidence Gate + 原子提交

---

### Task 7: 门禁全景复核与交付 PR [Tier: 1-Light] [Mode: AFK] [Role: Cleaner]

**Files:**
- Modify: `WORKMEMORY/work.log` · `docs/reviews/2026-10-16-open-items-backlog.md`（C6 行）

**Step Breakdown:**
- [ ] **Step 1**: 逐字复刻 CI 门禁命令：`mypy --strict delector tools`；`mypy --follow-imports=skip tests`；`ruff check .`；`cd agent && go test ./... -count=1 && gofmt -l .`
- [ ] **Step 2**: **全量 pytest（本工作流的核心验收）**：`python3 -m pytest tests/ -q`，通过数 MUST ≥ 搬迁前基线
- [ ] **Step 3**: 收集总数守恒终核：`python3 -m pytest tests/ --collect-only -q | tail -3` 与最初基线逐字相等
- [ ] **Step 4**: CRLF 卫生（0 lone LF）
- [ ] **Step 5**: 追加 `WORKMEMORY/work.log` DONE 事件
- [ ] **Step 6**: 推送分支并创建 PR（base=master）

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown 1: `Phase A/B/C` 是否真有执行顺序依赖]**：这三段（`test_server.py:1335/1423/1481`）可能共享同一 DB 状态。**若 Task 3 单独跑红，则顺序依赖成立** —— 届时需把依赖显式化（例如提供局部 fixture 复现同一前置状态），而**不是**把它们留在同一文件里回避问题。这条依赖的解法见 Task 3 的红线，不预先投机设计。
- **[Unknown 2: `test_server.py` 最终是否应完全清空/删除]**：Task 5 后该文件可能只剩零星段或无内容。**保留空壳**还是**删除**待 Task 5 实测残留量后裁决（若有残留则保留并改名，若无残留则删除并确认收集总数守恒）。
- **[Unknown 3: `test_desktop_shell.py` 的域划分]**：见 Task 6 第 1 步——2819 行的分段结构未实测，域清单不预先指定。
- **[Unknown 4: 是否有其它测试模块隐式依赖 `test_server` 的模块级副作用]**：Task 1 第 2 步的 grep 会揭示外部 import；但「不 import 却依赖收集顺序」这类隐式耦合只能靠全量跑两次对比发现。Task 1 与 Task 7 各跑一次全量即为该探测网。

---

## 🚫 Out of Scope

- **不做 `tests/test_german_workbench.py`**：已划归 C7 独占（其重写是 C7 的前置）。
- 不改任何断言语义、用例名、参数化取值（只搬归属）。
- 不引入 `pytest-xdist` / `pytest-randomly` / `pytest-order` 等插件来「解决」顺序问题——顺序依赖被暴露时应当**显式化**，而不是靠插件随机化掩盖。
- 不动 `delector/**`、`.github/**`、`static/**`（分属 C8 与 C7）。
- 不新增业务用例；只允许因搬迁必需的 import 头与（若有）共享层自身的单测。

---

## 🆕 追加项（来自 C9 终审，C6 执行者 MUST 处理）

### Task 0: 修正 `tests/test_server.py:2501` 的空转补丁（C9 移交的真发现）

**发现路径**：C9 的新机械闸 `tools/check_mock_drift.py`（判据 = 测试补丁的目标符号在生产模块内已无可达引用且非自供出口）在首扫中命中此处；经 C9 复核确认为**真遗留空转补丁**，非合法形态。

**实测事实**：`tests/test_server.py:2501` 对 `server`（`delector.server`）patch `nlp`。而 `delector/server.py` 的 `nlp` 是**裸外来再导出**（import 绑定 + `__all__` 兼容条目），模块自身不消费（`server.py:99-106` 注释自陈「handler 搬走后 server 自身不再消费」）。全仓**无任何消费方**读取 `server.nlp` ⇒ **该 patch 不生效**，用例实际读的是 `processor.nlp`（与补丁无关，故断言仍通过）。

**MUST**：在 C6 搬迁该用例时一并处置 —— 要么删掉这条无效 patch（若用例本就不需要它），要么改为 patch 真实消费面。**禁止**只搬不改，把空转补丁带到新文件里。

**当前状态**：该站点已在 C9 分支上带 `mock-drift-ok:` **过渡豁免**（理由里写明「真遗留空转、C6 修正」）。**C6 修完后 MUST 撤掉该过渡豁免**，让闸恢复对它的约束。

**验证**：修完后 `python3 tools/check_mock_drift.py` 在该站点上应仅在去掉豁免时触发；移除过渡豁免后闸仍须 exit 0。

---

## 📌 执行中登记的后续项（Task 5 交付时发现，不在本计划范围内）

### F1 · `__code__` 跨文件探针桥的根治（✅ 已于 2026-10-18 根治闭环）
原 `tests/test_server_settings_security.py` 中绑定 `__code__` 的探针桥已正式拆除。用例改为直接内省真实生产入口 `from delector.routes.main import ingest_from_url` 并断言其包含 `is_safe_public_url(req.url)` 安全门禁校验，彻底消除测试间的跨文件代码内省依赖。

### F2 · `test_server.py` 残余杂项区切分
- `GET /api/cards/counts`（3 用例 + `_insert_grammar_card`，原 1169-1258 行）：**✅ 已于 2026-10-18 归位至 `tests/test_server_cards_vocab.py`**（`test_server.py` 降至 52 用例，`test_server_cards_vocab.py` 增至 14 用例，全量 2355 严格守恒）。
- 剩余 876 行无 banner 的杂项区（writing / essays / CEFR / backup / audio-cache 等）保留在 `test_server.py` 作为残余综合测试区。
- **陈旧文档指针**：`package_windows.py`、`tools/verify_windows_portable.py`、`tests/test_desktop_port_guard.py` 中的测试位置指针**✅ 已于 2026-10-18 校正完成**。
