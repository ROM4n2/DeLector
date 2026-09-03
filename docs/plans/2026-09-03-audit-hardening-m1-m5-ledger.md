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
| M4 | M4-3 从句拓扑去重 | ⏭️ 跳过（计划允许，理由见下） | 见「决策记录」 |
| M5 收口 | M5-1 6 模块临时库隔离 | ✅ | goethe_a1/lesen/hoeren/writing、corpus、audit_regressions 顶部设 `DATABASE_PATH` + module 级清理 fixture；隔离库名进 gitignore（`*.db*`）；37 passed |
| M5 | M5-2 解析护栏 + 相对路径 | ✅ | `_top_fn_segment` helper 收敛 11 处 `split(声明)[1].split("\nfunction ")[0]`；改名标记变异演练显式红（DRILL OK）；writing 测试改 `Path(__file__)` 相对读文件 |
| M5 | M5-3 前端 P2 收口 | 🔶 部分完成（见下） | a1_lesen 计时器防叠 / pull 指数退避（5s→30s cap）/ rtc `disconnected` 瞬态不累计失败 三项已落地 + 结构护栏测试；LAN 按钮在途 disabled 与 ~30 处 `alert(` 批量收敛**未做** |
| M5 | M5-4 server `__all__` 收口 | ✅ | 剔除 `spacy/SPACY_MODEL_CANDIDATES/AUTO_DOWNLOAD_MODEL/_load_spacy_model/calculate_cefr_stats/_process_german_text_pure_python`（server 内无消费者，逐 token grep 核过）；保留 `nlp/NLP_ENGINE/NLP_ENGINE_DETAIL/SYSTEM_GRAMMAR_PROMPT`（有真实消费）。pyflakes 0 告警 + import 冒烟绿 |

## 本会话新增测试（test_audit_hardening.py）

- `test_lookup_core_vocab_hit_shared_no_news`、`test_split_komposita_cached_fresh_equal_results`、`test_m4_hot_path_lru_caches_structural`（M4-2）
- `test_m53_front_p2_debounce_and_pull_backoff_structural`（M5-3 结构护栏）

## 决策记录

1. **M4-3 跳过（高风险，计划允许带证跳过）**：`build_clause_tree` 每从句重算 `analyze_sentence_topology`
   的行为依赖整句 spaCy doc + 子句边界的局部修正，去重需先固化全量 golden 再做行为 diff，
   是 M4 中最敏感改动。按计划「若评估为不可安全去重，记录结论并跳过」处理：
   本批次优先落地了零风险的 M4-1/M4-2（常量提升 + 纯函数缓存，已覆盖读路径主开销中的
   大部分每次调用重建成本），M4-3 留待独立评审批次（需求：golden 快照 + 逐步下传 token 预处理）。
2. **M5-3 只完成了计划内的 5 项中的 3 项**：
   - ✅ `a1_lesen.startLesenTimer` 开头 `clearInterval`（防叠）；
   - ✅ `pull()` 失败指数退避（保留 `_busy`/防抖结构不动，用跳 tick 实现 5s→30s cap）；
   - ✅ `rtcOnStateChange` 仅 `failed/closed` 计入 `_rtcFails`（`disconnected` 视瞬态不累计，避免误降级）；
   - ⏳ LAN 同步按钮在途 disabled（`workbench.html` 旧版 btnLanOffer/btnLanAcceptAnswer 已属被
     Stage B `wbsync.rtc` 取代的旧面板，需要先确认当前活跃入口再改，避免改错面板）；
   - ⏳ `alert(` → `notify()` 批量收敛（当前 static/js + html 残留 **36 处**，目标 ≤5）：
     涉及 12 个模块，且 reader/writer 的若干 `alert` 文案/结构被 `test_writer_mobile.py`
     等字符串契约钉住，需逐点换 + 同步测试特征串 —— 适合独立批次完成，不宜在收尾仓促批量。
   承诺的目标测试（wbsync node 探针 + `startLesenTimer` 结构断言）已由新增护栏测试部分覆盖。

## 验证证据（本会话尾段）

- 纯规则模块整跑：`test_prep_matrix test_dict_pipeline test_audit_regressions test_syntax_tree test_writing_rules` = **78 passed**
- `test_server.py -k 'analyze or lookup or komposita or vocab'` = **23 passed**
- workbench/写作：`test_german_workbench.py test_goethe_a1_writing.py` = **87 passed**（`_top_fn_segment` 变异演练 RED OK）
- 前端：`test_frontend_module_graph / test_frontend_security / test_writer_mobile` = **45 passed**
- M5-1 六模块 = **37 passed**；M5-4 import 冒烟 + `test_audit_regressions + test_goethe_a1_lesen` = **11 passed**
- `pyflakes` 0 告警（server/linguistics/core_dict/nlp/syntax_tree）
- 本会话 commit：`187ae15`（M4-1 补遗）→ `4d7c1f6`（M4-2）→ `ac08fa3`（M5-1）→
  `635f5db`（M5-2）→ `96b19d8`（M5-3 前端三项）→ `9fea63e`（M5-4）

## 未完成 / 建议后续

1. M5-3 剩余两项（LAN 按钮 disabled 定位活跃入口后改；alert 收敛 ≤5 —— 建议立独立 Task）。
2. M4-3 如需做：golden 快照 → 尝试去重 → 行为 diff 全绿才提交（plan 已允许独立评审）。
3. 全量回归建议在可整跑环境执行一次（本环境因 safe-delete 守卫只做了定向子集）。
