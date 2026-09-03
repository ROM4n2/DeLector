# M1–M5 审计修复 · 执行 Ledger

> 计划：`docs/plans/2026-09-03-audit-hardening-m1-m5.md`
> 范围：2026-09-03 vault-team 全仓库审计（P1/P2）。执行期由**主线程直写**完成
> （本环境无写码子代理，vault-exec 降级声明见计划「执行模式说明」，本 ledger 原样保留，不伪造子代理记录）。
> 执行日期：2026-09-03。任务进度复核：M1–M2–M3、M4、M5 详见下表。

## 执行方式

- TDD 纪律：可测行为先 RED（定向 `-k`）→ 实现 GREEN → 受影响旧用例定向回归 → 原子 commit。
- 禁止裸跑全量 pytest（safe-delete 守卫）→ 全部用「受影响文件 / `-k` 定向子集」验证。
- 每 Task 一个 commit（`fix|perf|refactor|test(scope): 中文`）。

## 完成情况总表

| Milestone | Task | 状态 | 证据 / 备注 |
|---|---|---|---|
| M1 安全止血 | M1-1 还原备份白名单拆分 | ✅ | 还原导入只放行 TTS_VOICE/RATE，API_BASE_URL/API_MODEL 永不被恶意 payload 覆盖；DEEPSEEK_API_KEY 表内仍存 |
| M1 | M1-2 X-WB-Key 恒定时间比较 | ✅ | 三端点（wb state / sync store / rtc signal）统一 `verify_wb_key`（`secrets.compare_digest`） |
| M1 | M1-3 批注删除补本机闸 | ✅ | LAN client 删除 403 / 127.0.0.1 200；旧用例迁移到回环 client |
| M1 | M1-4 TTS 错误收敛 + voice 白名单 + 长度上限 | ✅ | 恶意 voice 400、超长 422、失败 500 响应不含内部异常文本；note-assist LLM 输入截断 |
| M1 | M1-5 Anki 导出 HTML 转义 | ✅ | 用户可注入字段先 escape 再拼 `<b>` 高亮，防存储型 XSS |
| M2 DB/连接 | M2-1 索引迁移（主 5+进度 2） | ✅ | 幂等 `CREATE INDEX IF NOT EXISTS`，按列断言 |
| M2 | M2-2 stats/趋势/streak 单扫描 | ✅ | 响应形状零变化；streak 保持「today 有记录才累计」原语义 |
| M2 | M2-3 list 只读免重算 + review 免回查 | ✅ | 惰性 stats 迁移只留 `GET /api/articles/{id}`；list 桩抛异常也能列文章 |
| M2 | M2-4 连接确定性关闭（database→server 两步） | ✅ | `db_conn`/`db_progress_conn` contextmanager，finally `_close_db_conn`；连接计数探针 0 泄漏 |
| M3 前端 | M3-1 notify 通知带 + api 超时 | ✅ | `core.js notify/api(timeoutMs=15000,signal)`；读路径原始错误不再上屏 |
| M3 | M3-2 陈旧响应守卫 | ✅ | reader 文章、writer 分析、cards 搭配矩阵加请求令牌/守卫 |
| M3 | M3-3 blob URL 生命周期 + 请求令牌 | ✅ | 暂停/切句/兜底统一 revokeObjectURL；`_reqToken` 防错句覆盖 |
| M3 | M3-4 PWA 温和更新 | ✅ | 去掉 `client.navigate` 硬刷；广播 `postMessage` + 页面提示「点击刷新」 |
| M4 NLP 热路径 | M4-1 常量/正则提升 | ✅ | writing_rules（4 冠词表、A1 判题词表/日期正则、email 词表）、linguistics（复数表/前缀）、nlp（CEFR 后缀元组）、syntax_tree `_ABBR_PATTERN`（补遗 commit `187ae15`）。纯规则模块整跑绿 |
| M4 | M4-2 缓存纯函数 | ✅ | `split_komposita` JSON 背衬 lru（`_split_komposita_json_cached`，返回全新对象防共享变异）+ `lookup_core_vocab` 命中共享条目（`_core_entry_cached`，调用方逐点审计仅读）。RED→GREEN：`test_lookup_core_vocab_hit_shared_no_news` / `test_split_komposita_cached_fresh_equal_results` / `test_m4_hot_path_lru_caches_structural` |
| M4 | M4-3 从句拓扑去重 | ⏭️ 跳过（评审确认，非「没空做」） | 组合路径每句仅一次 spaCy 解析、从句级调用走 clause_tokens 纯 Python 分支，原假设不成立；去重需切分+分配深度耦合重写且无 golden 快照。见 `docs/plans/2026-09-03-m4-3-clause-topology-dedup-review.md` |
| M5 收口 | M5-1 6 模块临时库隔离 | ✅ | goethe_a1/lesen/hoeren/writing、corpus、audit_regressions 顶部设 `DATABASE_PATH` + module 级清理 fixture；隔离库名进 gitignore（`*.db*`）；37 passed |
| M5 | M5-2 解析护栏 + 相对路径 | ✅ | `_top_fn_segment` helper 收敛 11 处 `split(声明)[1].split("\nfunction ")[0]`；改名标记变异演练显式红（DRILL OK）；writing 测试改 `Path(__file__)` 相对读文件 |
| M5 | M5-3 前端 P2 收口 | ✅ 全项完成 | 计时器防叠 / pull 指数退避（5s→30s cap）/ rtc `disconnected` 不累计（`96b19d8`）；旧短码 LAN 面板停用标注+按钮整体禁用（`61391b1`，端点 M1-2 起强制 X-WB-Key、面板不带 key 必 403）；AI 判分/成功提示类残余 alert→notify、写路径保留并加双面护栏（`c492f43`） |
| M5 | M5-4 server `__all__` 收口 | ✅ | 剔除 `spacy/SPACY_MODEL_CANDIDATES/AUTO_DOWNLOAD_MODEL/_load_spacy_model/calculate_cefr_stats/_process_german_text_pure_python`（server 内无消费者，逐 token grep 核过）；保留 `nlp/NLP_ENGINE/NLP_ENGINE_DETAIL/SYSTEM_GRAMMAR_PROMPT`（有真实消费）。pyflakes 0 告警 + import 冒烟绿 |

## 本会话新增测试（test_audit_hardening.py）

- `test_lookup_core_vocab_hit_shared_no_news`、`test_split_komposita_cached_fresh_equal_results`、`test_m4_hot_path_lru_caches_structural`（M4-2）
- `test_m53_front_p2_debounce_and_pull_backoff_structural`（M5-3 结构护栏）

## 决策记录

1. **M4-3 跳过（已评审确认，非「没空做」）**：原假设「每从句重算整句 topology（可能二次
   spaCy）」在生产读路径不成立——`process_german_text`/`_analyze_syntax_tree_doc` 均以
   `doc.sents` 的 Span 传入，spaCy 每句恰一次；从句级 `analyze_sentence_topology`
   （syntax_tree.py:1143）走 `clause_tokens` 分支纯 Python 字段分配。残余可去重面
   是每从句 O(子句长) 常数扫描，去重需把依赖整句依赖树的子句切分与按 `clause_type`
   覆盖分配的五字段算法深度耦合重写，无 golden 快照时行为回归面不可控。替代的零风险
   优化已同批落地（M4-1 常量/正则提升、M4-2 split_komposita/lookup_core_vocab 缓存）。
   详见 `docs/plans/2026-09-03-m4-3-clause-topology-dedup-review.md`。
2. **M5-3 全项完成**（原只完成 3/5）：
   - ✅ `a1_lesen.startLesenTimer` 开头 `clearInterval`（防叠）；
   - ✅ `pull()` 失败指数退避（保留 `_busy`/防抖结构不动，5s→30s cap）；
   - ✅ `rtcOnStateChange` 仅 `failed/closed` 计入 `_rtcFails`（`disconnected` 视瞬态）；
   - ✅ **旧 6 位短码 LAN 面板停用**（`61391b1`）：M1-2 起 `/api/wb/sync/store|fetch`
     强制 X-WB-Key，旧面板请求不带 key → 必 403，属死 UI。处置：`lanDisableLegacyPanel()`
     启动即整体禁用按钮 + 面板说明改为停用原因并引导到「镜像自动同步」；面板代码保留
     供回滚。新护栏 `test_workbench_legacy_lan_panel_disabled` 防复活忘鉴权。
   - ✅ **alert→notify 收敛**（`c492f43`）：按 M3-1 固化规则「读/抓取/AI/后台路径错误与
     轻量成功走 notify，写路径/输入校验保留 alert」逐点分类。本轮转 notify 8 处：
     AI/判分失败（reader 语法剖析、a1_lesen/a1_hoeren/a1_writer/cloze 判分）+
     成功/轻量提示（main 设置保存成功、cards 缓存空/清理成功）；写失败/输入校验/
     「成功+紧随 reload」28 处保留。静态残留 alert 36→28（余者全部落保留区）。
     新护栏 `test_grade_ai_and_success_alerts_use_notify` 双面断言（notify 白名单 +
     写路径保留点）防回潮。

## 验证证据（本会话尾段）

- 纯规则模块整跑：`test_prep_matrix test_dict_pipeline test_audit_regressions test_syntax_tree test_writing_rules` = **78 passed**
- `test_server.py -k 'analyze or lookup or komposita or vocab'` = **23 passed**
- workbench/写作：`test_german_workbench.py test_goethe_a1_writing.py` = **87 passed**（`_top_fn_segment` 变异演练 RED OK）
- 前端：`test_frontend_module_graph / test_frontend_security / test_writer_mobile` = **45 passed**
- M5-1 六模块 = **37 passed**；M5-4 import 冒烟 + `test_audit_regressions + test_goethe_a1_lesen` = **11 passed**
- M5-3 收尾：alert/notify 定向 **3 passed**；`test_frontend_module_graph + test_writer_mobile
  + test_frontend_security + test_german_workbench` = **124 passed**；LAN 面板护栏 **1 passed**
  （workbench 全量 79 passed 单独验证）
- `pyflakes` 0 告警（server/linguistics/core_dict/nlp/syntax_tree）
- 本会话 commit：`187ae15`（M4-1 补遗）→ `4d7c1f6`（M4-2）→ `ac08fa3`（M5-1）→
  `635f5db`（M5-2）→ `96b19d8`（M5-3 前端三项）→ `9fea63e`（M5-4）→ `c492f43`
  （M5-3 alert 收敛）→ `61391b1`（M5-3 LAN 面板停用）

## 未完成 / 建议后续

1. 全量回归建议在可整跑环境执行一次（本环境因 safe-delete 守卫只做了定向子集，
   M1–M5 各定向子集均已绿）。M4-3 若未来仍要推进：先固化全量 golden 快照再谈行为 diff
   （评审文档第 4 节已列前置条件）。
