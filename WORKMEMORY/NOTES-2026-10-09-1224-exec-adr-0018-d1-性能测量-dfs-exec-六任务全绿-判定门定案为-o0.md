### 2026-10-09 12:24 | codebuddy | EXEC(ADR-0018 D1 性能测量) /dfs-exec 六任务全绿、判定门定案为 O0

> 本文件是 `WORKMEMORY/work.log` 中该事件的**正文**（原事件 5882 B，超 `PROTOCOL.md` §4 的 4096 B 上限）。
> 拆分时间：2026-10-14；正文逐行无损搬运，未删改任何内容。

Caps: filesystem-read, filesystem-write, shell-exec
事件：按 `docs/plans/2026-10-09-performance-measurement.md` 走 `/dfs-exec`，maker-checker 逐任务派单（implementer=CPE，checker=CRV），分支 `perf/measurement-baseline`（先合 ADR-0018 于 master `6a58759` 再开分支，规避决策文档/exec 分支撞车）。**只加测量工具与门禁，零生产代码改动**（五个基准脚本 + 五个门禁）。
- **交付（6 commit）**：`4380dca` 卡盒补 Python 侧占比与阈值闸 → `f9b90cb` spaCy 单价基准 → `60fc045` 长文冷/热读基准 → `b924ad6` 冷启动基准 → `5409ac2` 分层剖析汇总 + p95 补测 → 本次文档收口。
- **⭐ 判定门定案（本轮的交付物）**：条件① **成立**（加权 Python CPU 代理占比 **85.9%**：卡盒 84% / 长文 98%）；条件② **不成立**（四场景 p95 距 2× 目标余量：卡盒 **0.35×**、冷启 0.26×、长文冷读 0.02×、热读 0.0001×）⇒ **AND 门不成立 ⇒ 走 O0（维持现状 + 便宜杠杆）**，**不做** O2（热点下沉）也不做 O3（扩展 ADR-0008 边界）。实质：Python 侧占比高只说明"若要优化就该优化 Python 侧"，**不说明现在必须优化** —— 绝对延迟离目标还有 2.9~40 倍余量。
- **统计纪律（防"拿中位数冒充 p95"）**：默认 n=5 档只输出"**仅可否证**"（n=5 的经验 p95 ≈ 最大值，`P(max₅ < 真p95) ≈ 77%` ⇒ **系统性低估尾部**）；只有 `BENCH_P95_ROUNDS=20` 档（n≥20）才允许写"不成立"这类强结论。三基准 p95 均复用**已采集的同批样本**（不重新计时，时间增量 0）并输出原始样本行。
- **实测数字**：卡盒端点 p95 **0.696s**（Python 侧 84%，SQL filesort 仅 3~5% ⇒ 查询侧优化收益上限被压死）；长文冷读 **122ms**（12 句）/ 热读 **17.7µs** ⇒ 缓存生效（数量级 ~6.9e3，非算法加速倍数）；spaCy 稳态 **7.1ms/句**（`de_core_news_sm`，≈296µs/token），首次/稳态仅 **1.3×**；冷启动 `health_200` **2.6s**（import 2.1s，其中 **spaCy 模型加载 1.47s 占首启 57%**）。
- **⭐ spaCy 单价 20 倍矛盾 → 重新定性为"跨口径"而非"有一个错值"**：`syntax_hard.py:9` 的 42ms 与审计的 2.1ms 指向 **rank_sentences→analyze_syntax_tree** 路径，本次实测的是 `process_german_text`（完整管线）**不是同一个函数** ⇒ 两者**不可直接相除**，"实测/2.1 = 3.4×"属跨函数差。**未完成项**：要修订那条 42ms 注释，**必须先补测 rank_sentences 单价**（checker 抓出我原任务书里就存在这个跨口径混用）。另：42ms 的候选解释（① md 口径 ② 含冷启动摊薄 ③ 整篇含 DB 写入）**均未定案**；其中"摊薄 ⇒ N≈42 句"**不构成证据**（该方程对任意 steady<42 恒有正解、N 是自由参数、分子含词库 import 换机即变，属单位巧合）。
- **checker 三轮抓到的非风格缺陷（都被收口）**：① Task 1 的 `_python_verdict` 在 >50% 时直接写"走热点下沉"，而 ADR §6 是**双条件 AND**（还差 p95）⇒ **结论越权**，改为只报条件①；② Task 2 结论**跨口径相除**（见上）+ "冷启动摊薄"假说**不可证伪却写成断言**；③ Task 3 未声明走哪条 NLP 路径（spaCy 不可用时会**静默降级到纯 Python** 而 `spacy_ms` 照常打印 ⇒ 输出整体失真），与"测不出必须写 unmeasured"同一条纪律。
- **⚠️ 测量顺带发现的生产代码缺口（本计划不改，仅登记）**：`delector/core/database.py:91-93` 的数据目录迁移闸条件① 用 `isfile` **不看 size**，而"0 字节不算数据"的判定只作用于**旧位置** ⇒ **新位置放 0 字节 delector.db + 旧位置有真实数据 ⇒ 闸静默放行**，正是它自己要防的"静默空库"。现有用例只覆盖"0 字节在旧位置"（`tests/test_data_dir_migration_gate.py:98`）⇒ 新位置这条**无用例**（本基准正是靠这个不对称通过迁移闸，已用 `data_dir_gate_note` 写明）。另：`invalidate_rank_cache()` 只清聚合键是 **docstring 明确论证的有意取舍**，经独立核实**无害**（材料入库后不可变 + id 不复用），**不改**。
- **未测项（各附原因，不伪造数字）**：网络层（AI 需 key；TTS 免 key 但属第三方服务；RSS 公开免 key 但会给 CI 引入外网抖动 ⇒ **选择**不发外部请求，且对四场景贡献为 0）；前端渲染（无浏览器自动化基线，需 Chrome DevTools 手工录制）；Windows RSS（无 stdlib `resource`，且不为测量新增 `psutil`）；Android 全项（本机无 SDK；84000ms 是**轮询上限**而非实测首启，与桌面 `health_200` 不同口径、**不可相减/相除**）。
- **⚠️ 结论依赖未确认的假设目标值**：`target_cold_start_s=5.0` / `target_long_read_cold_s=3.0` / `target_cards_list_s=1.0` / `target_warm_read_s=0.1` 是**本基准的假设值**（输出以 `target_status=unconfirmed` + 每场景 `headroom_to_2x_target_*` 绑定声明）⇒ **条件②的"不成立"完全依赖它**，若用户给更严目标结论可能翻转。另：四场景是**代理口径**（`segment_D` 是进程内 SQL/物化段、非"列表+滚动端到端"；`health_200` ≠ 首屏可用），见 `scenario_scope_note`。
**门禁（分支实测，数字来自本次最终 commit 的本人实跑）**：半 A **1189** passed（基线 1106 + 83 新增：Task1 3 / Task2 22 / Task3 20 / Task4 21 / Task5 17）；半 B `test_server` **264** passed + 1 skipped；`tools/*_probe.mjs` **29** 个文件零失败（标准三键 9 / legacy 扁平 19 / 需传参 1）；`ruff check .` 0；mypy 两道 **100** + **77** files 零错误。

