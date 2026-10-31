---
title: "ADR-0010: 遇见区 i+1 阅读桥——分层架构，Go Agent 批量内容生产引擎"
created: 2026-09-07
updated: 2026-10-14
type: project
tags:
  - project/delector
  - topic/architecture
  - topic/agent
  - topic/product
status: stable
audience:
  - architect
source: "vault-grill 双镜拷打（Round 1–5）"
authority: synthetic
claim_risk: medium
review_status: unreviewed
---

# ADR-0010: 遇见区 i+1 阅读桥——分层架构，Go Agent 批量内容生产引擎

- **状态**: Accepted
- **日期**: 2026-09-07
- **作者**: Lead Socratic Inquisitor（vault-grill 双镜拷打，用户拍板 Option B）
- **领域**: Product Architecture / Go Agent Runtime / Python NLP 服务
- **拷打对象**: "Go 语言后端 + agent 开发"愿景 vs 真实用户（Android 背词，A1→A2）学习路径

---

## 1. 背景与问题定义 (Context & Problem Statement)

用户拍板的三个事实前提：

1. **真实用户**（作者女友）主要用安卓端背词工作台背词；当前水平（A1→A2）不足以读文章，
   **但学习路径的下一步必然是"从背孤立词过渡到在短文本里遇见已背词"**——这是要开发的"下一步"。
2. **跨端需求**：电脑上背词已被既有 PyInstaller 桌面 Release 覆盖（免装双击）；跨端数据同步
   只需同一 WiFi 的 LAN 对等同步（Q2=A）——**不建跨网 hub，桌面分发不重造**。
3. **作者愿景**：做"Go 语言后端 + agent 开发"。Phase 2a/2b（`agent/` module：supervisor/DAG/registry/
   llm client/绿色便携包/三平台 CI）全部就位，但 **DAG 只装配从未执行、DeepSeek 未接线**——
   agent 目前是无用户闭环的壳；同时，"分发"叙事被既有桌面 Release 证伪为伪增量。

核心张力：作者想要的 Go+agent 愿景与产品真实需求**只有在"重批处理/编排"这一层才诚实重叠**。
交互请求（标注已背词、生词进卡）是 Python 近数据近设备的活，硬搬 Go 只是加一跳（YAGNI 违背）。

## 2. 决策驱动因素 (Decision Drivers)

- **用户（产品镜）**：为她的背词→阅读过渡造一座桥——**"遇见区"**：分级短文本（难度 = 她水平 +1，
  i+1 可理解输入）；已背词在文中高亮，1–2 个生词一键进卡，读完小复习。功能在她达到阅读期前就位。
- **技术/作者（工程镜）**：让 `delector` 的 DAG **真正执行第一个 job**（批处理语料→分级卡包生产），
  Go 从此从壳变能力；DeepSeek 走既有 go llm client；复用 Python `tools/` TOOL_REGISTRY 作 leaf worker。
- **复用阶梯（MUST）**：Python 599 测试核心零重写；spaCy 形态学/本机词库匹配不搬 Go；
  交互 Web 路由不搬 Go。新增 Python 面最小化（1–2 个 leaf 工具 + 1 条 route）。
- **运维面**：已有三平台 CI / 绿色便携包 / supervisor 常驻 —— Go 批处理 worker 可跑在作者桌面
  或她电脑的绿色包里，产物经 HTTP 喂给 Web 端。

## 3. 备选方案 (Considered Options)

| 方案 | 说明 | 否决理由 |
|---|---|---|
| **A 纯 Python 遇见区** | 遇见区全部在 FastAPI 内做，Go agent 冻结作品态 | 用户价值快，但作者 Go+agent 愿景零推进，本轮已放弃 |
| **B 分层（选定）** | Web 管交互；Go agent 管批处理内容生产（DAG job#1） | ✅ 采纳 |
| **C 纯 Go demo** | 与产品解耦的演示流水线 | 炫技，不用户价值，否决 |

## 4. 决策 (Decision Outcome)

**采用分层"遇见区"架构，Go 边界尽量前压（用户明确 Option B + "尽量靠拢 Go 后端和 agent"）**：

- **北星功能「遇见区」**：Web 侧交互体验（取文→展示→已背词高亮→生词一键进卡→小复习），
  安卓 WebView 与桌面同步受益；P0 先用手选短文本上线，保证她到阅读期时功能已在。
- **Go agent = 批量内容生产引擎**：`delector` 新子命令/工作模式跑 **真 DAG job#1**：
  语料（RSS 文库/本地目录）→ 队列/去重/调度 → 跨文章并发 → 每篇 DAG：
  `ingest → analyze（形态/已背词统计，Python tool）→ gloss/定级（DeepSeek，Go llm client）→ export（分级卡包 JSON）`
  → 产物喂给「遇见区」。**这是 Phase 2b CRV 明示"归后续 Task"的 DAG 真执行语义首次落地。**
- **DeepSeek 职责**：难度定级 + 生词释义（Go 侧 llm client 直调；Python 侧不重复接 LLM 管线）。

## 5. Go/Python 边界 (Boundary, the "尽量靠拢"硬分界)

| Go 拥有（编排/重活） | Python 保留（算力/近数据） |
|---|---|
| 语料队列/去重/调度、跨文章并发、退避重试（supervisor 复用） | spaCy 形态学、lemmatization、已知词库匹配 |
| DAG 真执行（首个 job） | 交互请求路由（`/api/encounter/...`，近用户设备与本机 DB） |
| DeepSeek 定级/释义（go-openai） | 既有 TOOL_REGISTRY leaf 工具作 HTTP worker |
| 卡包组装、产物落盘/投递 | 599 测试核心（零重写） |

**红线**：交互请求不加 Go 代理跳；已知词判定不离开本机 DB；不建跨网 hub；桌面分发不碰。

## 6. 后果与代价 (Consequences)

- **正面**：agent 获得第一个真实用户闭环；DAG/并发/supervisor/llm/绿色包全部第一次连成产品链路；
  她的阅读期过渡有 i+1 内容供给引擎。
- **代价**：Go 侧需实现 DAG **执行运行时**（Phase 2a 只写了调度与拓扑验证，未写 step 执行语义
  的端到端消费）；需要 1–2 个新 Python leaf 工具（含"已知词匹配/定级统计"，DB 查询在服务端工具内）；
  DeepSeek 调用有 token 成本（批量需限流/预算护栏）；遇见区 P0 手选短文本语料要人肉准备。
- **递延/不做**：跨网 hub（Q2=A）；agent 替换桌面版（PyInstaller 已覆盖分发）；把交互层搬 Go（YAGNI）。

## 7. 实施顺序（共识，供 /vault-plan 拆解）

1. **P0 遇见区最小版（Python 侧）**：手选短文本上线，验证背词→阅读桥 UX 与安卓可用性。
2. **Go DAG 执行运行时 + job#1**：语料→分级卡包批处理流水线（真执行、DeepSeek 定级/释义、
   产物经既有工具/新端点投递），喂饱遇见区语料。
3. 验收门：Python 全量测试零回归 + `go test -race ./...` + `-tags integration` 真 DAG→工具→LLM(stub) 链路
   + 遇见区在桌面 Release 与安卓双端可用。

## 8. 相关 (References)

- ADR-0008（DAG 4 层口径修订）— 计划状态块锚点；ADR-0009（Python 工具契约）— leaf 工具语义依据。
- `docs/plans/2026-09-06-go-agent-runtime-phase2a/2b.md`（supervisor/DAG/registry/llm/打包全部就位）。
- Vault：`08-Projects/DeLector/GO-PYTHON-HYBRID-ARCHITECTURE.md`（进程坑/打包校准 §5.1/§6）。
