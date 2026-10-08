# ADR-0018: 性能前提先测量，Python 主体不换（热点下沉策略）

> **正式件:** `08-Projects/DeLector/01-ADR/0018-performance-measurement-before-runtime-swap.md`（vault）。本文件是仓内副本，内容与正式件同源。
> **决策者:** Haoyu Xi ｜ **产出方式:** `/dfs-grill` 双镜拷问（code-explorer 事实核查 + perf-profiler 实测席位）+ 用户拍板

- **状态**: Accepted（2026-10-09）
- **实施**: **待执行**（本 ADR 的第一动作是"测量"，尚未跑）
- **日期**: 2026-10-09
- **领域**: 性能工程 / 架构边界 / 多形态打包
- **决策者**: Haoyu Xi
- **上游**: **ADR-0008**（Go Agent Runtime + Python NLP Engine 混合架构）、**ADR-0010**（Go/Python 边界：Go 拥有编排/重活，Python 保留算力/近数据）、ADR-0016（统一词池）、ADR-0017（更新可见性）
- **本 ADR 的定位**: **不推翻** ADR-0008/0010，而是**澄清其边界** —— 明确"Python 继续作为 HTTP 主体"，并给"什么时候才允许动它"设闸门。

---

## 1. Context

### 1.1 提案原文

> 不用 Python 换用更高效的作为系统能不能实现？我只想 Python 利用它的生态库，来调用其他德语或者记忆算法相关部分。不希望它的性能等等拖垮项目。

即：系统主体换更高效语言（Go/Rust），Python 降为"被调用的生态库层"（德语 NLP、记忆算法）。

### 1.2 现状（已核实，非推测）

- **三形态共用同一后端**：桌面 Python（`start.py` → `127.0.0.1:8000`）、Windows 便携版（PyInstaller `--onedir --console`）、**Android（Chaquopy：APK 内嵌 Python 3.10 + spaCy 3.8.7 + `de_core_news_sm`，arm64-only，56.7MB）**。
- **spaCy 是硬依赖**：德语 NLP 只有 Python 生态；Android 上以 Chaquopy wheel 形式装载。全仓**无**任何 WASM / Cython / Rust 扩展，Python 侧"原生"成分全部来自第三方 wheel（thinc / blis / numpy / cymem / preshed / murmurhash）。
- **项目已有 Go 代码且已有架构决策**：`agent/` 是 **ADR-0008 的 Go Agent Runtime**（CLI + DAG 编排 + supervisor，依赖 go-openai / cobra），它**拉起** `uvicorn` 子进程（8001）。**方向恒为 Go→Python**：主应用**不调用** Go（`delector/routes/main.py:2575` 仅有一处注释反向提及）。ADR-0010 已划边界：Go 拥有（语料队列/去重/调度、跨文章并发、退避重试），Python 保留（spaCy 形态学、lemmatization、已知词库匹配）。
  ⇒ **"把重活给更高效语言"这条路已经存在并已决策**，真正的待决问题是"**要不要把 HTTP 主体也搬过去**"。

### 1.3 性能证据盘点（关键：证据不足）

| 证据 | 位置 | 强度 |
| --- | --- | --- |
| 唯一真基准脚本 | `tools/bench_cards_endpoint.py`（CI 以 `BENCH_SCALES=8000 BENCH_ROUNDS=5` 实跑） | **只断言结构与开区间，不钉性能阈值** ⇒ 无回归闸 |
| 卡盒成本实测 | perf 席位：20k 卡 790ms，其中 **Python/FSRS 84%**、排序 9% | 单场景，未建模端到端 |
| 审计文档数字 | `docs/reviews/2026-10-03-swarm-audit-master.md`（save_wb_state 4.9/27.0/154.5ms；WAL p99 434ms 等） | **不可复跑**，部分自带 `UNVERIFIED` 标注 |
| spaCy 单价 | `syntax_hard.py:9` 注释写 `~42ms/句`；`docs/reviews/2026-09-28-swarm-audit-master.md:36` 写 `实测 ~2.1 ms/句` | ⚠️ **同一量两个值差 20 倍，都没有可复跑脚本兜底** |
| GIL 感知点 | `ExportSaver.java:73`「单线程串行：服务端是单 worker uvicorn + GIL」 | 全仓**唯一**点名 GIL 处 ⇒ 只在"大导出并发"被感知 |

**结论**：「Python 性能拖垮项目」目前是**直觉，不是测量**。

### 1.4 瓶颈排序（perf 席位，附证据强度标注）

**AI/TTS（网络 IO）> spaCy（Cython/C）> SQLite（IO）> 冷启动 > 前端渲染 > HTTP/序列化**

前两项一个卡在网速、一个卡在 C 扩展 —— **都不是解释器速度的锅**。

---

## 2. Decision Drivers

### 2.1 用户与技术（User & Product）

- **U1 体感而非架构审美**：要修的是具体慢点（启动、长文精读、卡盒滚动），不是"用 Python 不高级"。
- **U2 不可逆性**：换 HTTP 主体是三形态的大改造（尤其 Android 打包），在没有测量支撑前做是不可逆的赌博。
- **U3 不因担心丢功能**：`package_windows.py:51` 的 `--console` 是为 LAN IP 提示服务的（ADR 类比：任何"顺手去掉"都可能砍功能）。

### 2.2 技术与系统（Technical & Systems）

- **T1 测量先行**：判定标准必须可复跑（对照 `bench_cards_endpoint.py` 只断言结构的教训）。
- **T2 换语言不解决最大瓶颈**：网络 IO 与 spaCy 本身都不受宿主语言影响。
- **T3 Android 双运行时代价**：现 APK 已内嵌 Python（56.7MB）；再引入 Go（带 runtime）或 Rust（需 per-ABI 编译，现只 arm64）＝双运行时，涉及体积、首启解包、CI 复杂度。
- **T4 单一真相源纪律**：新增任何性能常量/阈值必须可复跑，不得再造"文档里的数字"（同 v5.16.0 的 `PROCESSED_JSON_VERSION` 判据漂移教训）。

---

## 3. Considered Options

### 3.1 Option O0：维持现状 + 便宜杠杆（**基线，非终态**）
NLP 结果缓存、批处理、`de_core_news_sm/md` 选择、惰性加载、卡盒预计算分页。
其中"重复 NLP"已被 v5.16.0 证实真实存在（判据漂移 ⇒ 每次 GET 重跑 spaCy）。

### 3.2 Option O1：换 HTTP 主体（Go/Rust 重写路由与业务，Python 降为 NLP sidecar）—— ❌ **否决**
否决依据（三条，任一成立即否决）：
1. **spaCy 不可移除** ⇒ NLP 调用从"同进程函数调用"退化为"跨进程/IPC"，**多一跳**；而 spaCy 本身是 Cython/C，换宿主不会让它更快。
2. **最大瓶颈不受影响**：AI/TTS 网络 IO 与 spaCy 计算都不因宿主语言改变。
3. **Android 双运行时**：现 APK 已 56.7MB 内嵌 Python；再加一套运行时（体积/首启解包 30MB/CI/ABI）与"三形态共用同一后端"的既有约束直接冲突。

**翻盘条件（写入本 ADR 以防悄悄重开）**：测量结果同时满足 —— ① Python **解释器开销**（剔除 spaCy 与 IO 后）占请求 p95 的 >50%；② 热点下沉（O2）实测无法压到目标以下；③ Android 侧双运行时方案已给出可接受的体积与首启数据。**三者缺一不可，且需另开 ADR。**

### 3.3 Option O2：热点下沉（Rust/Go 写成扩展给 Python 调用，Python 仍是主体）—— ✅ **条件采纳**
只把**实测出的热点**（如 FSRS 递推、排序、搭配提取）用 PyO3 / cgo / C ABI 下沉。
优点：单运行时、体积几乎不变、收益集中在真瓶颈、可逆。
代价：每下沉一个热点引入一条构建链路（对 Android 而言需交叉编译到 arm64）。

### 3.4 Option O3：扩展既有 ADR-0008 边界（Go Agent 承担更多编排/并发）—— ✅ **条件采纳**
把队列/批处理/并发/调度继续交给 Go，Python 保留 HTTP + spaCy。
优点：顺着既有决策走，增量最小，且**不新增调用方向**（现有已是 Go→Python）。
代价：Go Agent 目前未被主应用调用（需新增桥接）；双进程运维面扩大。

---

## 4. Decision Outcome

| 编号 | 决策 |
| --- | --- |
| **D1（Q1-A）** | **先测量，不换**。用 §6 的 1 小时方案取得可复跑数据，再决定下一步。**在此之前不动任何架构。** |
| **D2（Q2 按建议）** | 按测量结果选路：**Python CPU 主导 → O2（热点下沉）**；**编排/并发主导 → O3（扩展 ADR-0008 边界）** |
| **D3** | **O1（换 HTTP 主体）永久否决**，除非 §3.2 列出的三条翻盘条件同时成立且另开 ADR |
| **D4** | 测量**之后**默认先做 O0 的便宜杠杆（尤其"重复 NLP"类），再评估是否需要 O2/O3 |
| **D5** | 明确写入：**Python 不可移除**（spaCy 硬依赖）；本 ADR 讨论的永远是"边界"而非"替换" |
| **D6** | 测量结果必须**可复跑**：新增基准须像 `bench_cards_endpoint.py` 一样进 CI，且**必须钉阈值**（补上现基准"只断言结构"的缺口） |

---

## 5. Consequences

### 5.1 正向
- 避免在"42ms vs 2.1ms"这种矛盾地基上做不可逆决策。
- 顺带补上一个真实缺口：**现唯一基准不钉性能阈值** ⇒ 测量产物（带阈值的基准）本身就是长期资产。
- 与 ADR-0008/0010 同向，不新增架构分歧。

### 5.2 负向 / 代价
- 决策**延后**：至少 1 小时测量 + 可能的杠杆实施，才能推进"更快"这件事。
- 若测量后走 O2，Android 侧每个下沉热点都要处理 arm64 交叉编译（新增构建复杂度）。

### 5.3 中立
- 本 ADR 不改变任何生产代码；`agent/`（Go）维持现状（主应用仍不调用它）。

---

## 6. 落地：1 小时最小测量方案（D1 的执行规格）

**① 四个场景（端到端 p95）**
1. 冷启动（进程起到首屏可用）
2. 长文精读（长材料走 spaCy 全文分析）
3. 热读（同一材料二次访问 —— 验缓存是否生效）
4. 卡盒 20k 卡（列表 + 滚动）

**② 剖析层（每层占比）**
Python CPU / RSS / 前端渲染 / SQLite / 网络（AI·TTS·RSS）

**③ 判定阈值**
- **进入 O2/O3 的门**：Python CPU 占比 > **50%** **且** p95 > **2 倍目标**；
- **进入 O1 评估的门**：见 §3.2 三条翻盘条件（**更严**）。

**④ 产物（必须满足 T1/T6）**
- 可复跑的基准脚本（进 CI，**钉阈值**，不是只断言结构）
- 一份"各层占比"结论，写进本 ADR 的 §1.3 表（替换"证据不足"那一行）
- **顺带收口**：解决 spaCy 单价的 20 倍矛盾（42ms/句 vs 2.1ms/句），给出唯一可复跑值

---

## 7. Fog of War

- **[Unknown 1] 测量结果本身**：D2 的两条分支取决于它 —— 这是本 ADR 唯一的开放式未知，**不得在测量前预先选路**。
- **[Unknown 2] Android 侧如何测量**：本机无 Android SDK（Java 侧改动只能靠 CI 验证）；真机冷启动/首启解包 30MB 的体验成本如何量化，未定。
- **[Unknown 3] 卡盒前端渲染的占比**：perf 席位标注"排序未实测"，20k 卡 790ms 中前端部分未剖析。
- **[Unknown 4] O2 的 Android 交叉编译链路**：若热点下沉命中 Android，需 arm64 交叉编译 + Chaquopy 装载方式，方案未定（不在本 ADR 范围）。

---

## 8. 关联

- **上游**：ADR-0008（Go Agent Runtime + Python NLP Engine 混合架构）、ADR-0010 §5（Go/Python 边界"尽量靠拢"硬分界）。
- **同族教训**：v5.16.0 的 `PROCESSED_JSON_VERSION` 判据漂移（"重复 NLP"真实存在过一次）；`docs/reviews/2026-10-03-swarm-audit-master.md`（不可复跑数字的来源）。
- **执行口径**：`/dfs-grill` 产出 → 若进入实施，走 `/dfs-plan`（把 §6 拆成 TDD 任务）→ `/dfs-exec`。
- **知识库**：vault `06-Sources/Articles/GO-PYTHON-HYBRID-ARCHITECTURE.md`（Go+Python 混合架构两阶段策略：subprocess/HTTP）。
