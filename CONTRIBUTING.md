# DeLector 贡献指南 (Contributing Guide)

欢迎参与 DeLector 项目！我们是一个追求学术级严谨、工程化防御性架构与高可靠性的开源项目。无论你是提交缺陷报告、改进文档还是贡献代码，我们都非常感谢你的支持。

---

## 🛠️ 开发环境与准备工作

### 1. 技术栈要求
- **Python**: 3.10 或 3.11（推荐 3.11）
- **Go**: 1.22+（用于 `agent/` 目录下的 Go 智能体运行时）
- **Node.js**: 18+（用于运行 `tools/*.mjs` 动态行为探针）
- **系统环境**: Linux / macOS / Windows 10+ (需安装 Edge WebView2 运行时)

### 2. 初始配置与密钥守卫
克隆仓库后，**首要步骤**是启用仓库的提交前安全守卫钩子（全量密钥扫描与格式守卫）：

```bash
git config core.hooksPath .githooks
```

安装 Python 核心与开发依赖：

```bash
uv venv --python 3.11
uv pip install -r requirements.lock.txt
uv run --no-project python -m spacy download de_core_news_sm
```

启动本地服务调试：

```bash
uv run --no-project python start.py    # 启动 Web 服务并自动打开浏览器
uv run --no-project python desktop.py  # 启动 Windows 原生桌面窗口（pywebview 已含在 lock 中）
```

---

## 📐 工程红线与架构纪律

提交代码前，请确保严格遵守以下工程不变量：

1. **绝对单向分层与零架构污染**：
   - 后端必须严格遵守 `Layer 0 (core)` $\rightarrow$ `Layer 1 (db)` $\rightarrow$ `Layer 2 (nlp_engine)` $\rightarrow$ `Layer 3 (services)` $\rightarrow$ `Layer 4 (tools)` $\rightarrow$ `Layer 5 (routes)` 的单向引用层序。
   - 前端 L1 纯层（如 `rd-syntax.js` / `wr-format.js`）**严禁**接触 DOM、网络请求、定时器、用户弹窗或顶层可变状态。
2. **零构建 / 零运行时打包器依赖**：
   - 前端采用原生 ES Modules 与 Modern CSS。禁止引入 Webpack / Vite / Rollup 等前端打包流。
   - `static/index.html` 的修改必须维护 `static/layout/`、`static/views/`、`static/modals/` 中的分块模板，并运行 `python tools/build_index_html.py` 同步，由 `python tools/check_index_html_sync.py` 严格校验。
3. **零静默降级（Zero Silent Failures）**：
   - 严禁任何裸 `except Exception: pass`。任何异常吞没必须附带经过严格审查的 `# silent-ok: <明确理由>` 豁免标注。
4. **探针判别力保真与变异自证**：
   - 修改业务逻辑时，禁止通过降级或拓宽探针 seam 来制造假绿。新增规则必须具备变异自证能力（注入故障时必须报出预期的规则名并退出码非 0）。
5. **文件换行契约**：
   - 除 `.go` 文件保持 LF 外，全仓文本文件必须统一为 **UTF-8 CRLF**（0 lone LF）。

---

## 🧪 本地质量门禁与验证

在提交 PR 之前，必须在本地完整运行并确认以下门禁全绿：

```bash
# 1. 运行六道 Python 机械闸
python tools/check_frontend_layers.py
python tools/check_layer_invariants.py
python tools/check_mock_drift.py
python tools/check_silent_degradation.py
python tools/check_frontend_api_contract.py
python tools/check_index_html_sync.py

# 2. 静态分析与类型检查
python -m ruff check .
python -m mypy --strict delector tools
python -m mypy --follow-imports=skip tests

# 3. Go 门禁 (agent 运行时)
cd agent && go vet ./... && gofmt -l . && go test -race ./... && cd ..

# 4. 全量 Python 测试 (必须单条串行，避免并发争用数据库守卫)
python -m pytest tests/ -q
```

CI 闸门本身的时长、并发、缓存与新增 job 门槛见 [CI 闸门速度与并发预算](docs/agents/ci-speed-budget.md)。不得为提速删除真实检查，只能消除重复执行与无效开销。

---

## 🤝 分支与 PR 提交流程

1. **分支命名规范**：
   - 功能开发：`feature/<topic>`
   - 缺陷修复：`fix/<topic>`
   - 架构重构：`refactor/<topic>`
   - 流程工具与文书：`chore/<topic>` 或 `docs/<topic>`
2. **提交与 PR 规范**：
   - 遵循 Conventional Commits：`type(scope): 描述`。
   - 一个 PR 内应按可独立审查的逻辑边界拆分提交：后端 / 前端 / 契约 / 测试 / 文档分别成提交，不得把整批实现无差别压成一个巨型提交。
   - TDD 的 RED 与 GREEN 可以同属一个逻辑提交，但提交信息或 PR 描述必须写明实际测试证据；变异验证必须同时记录故障表现与还原后的复验结果。
   - 单提交超过 **10 个文件或 600 行改动**（任一项）时，应先主动拆分；若因生成物同步或跨端原子契约确实必须一次提交，必须在 PR 描述中解释不可分割的理由。该数值只用于作者自查，不设 CI 硬门。
   - 不新增按文件数/行数阻断或警告的 CI 作业：生成物、重命名和跨端契约天然会放大 diff，机械阈值容易制造噪声；提交粒度由作者自查与 reviewer 复核，现有测试与机械闸不为此增加额外运行面。
   - PR 模板中的各项检查项必须如实勾选并附带真实的本地门禁终端输出末行截屏/文本。
   - 实施计划与配套代码**必须放在同一个分支、同一个 PR 中原子交付**。
3. **开源授权契约**：
   - 凡向本项目提交的任何 Pull Request，除非作者在提交中作出显式例外说明，均默认依据 [Apache License 2.0](LICENSE) 条款进行授权贡献。
