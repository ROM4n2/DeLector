# Mypy Strict 类型门禁升级设计（2026-09-18）

> 定位：`docs/specs/`（设计文档）；执行清单与状态跟踪见 `docs/plans/2026-09-18-mypy-strict-annotation-sweep.md`（待建）。
> 上游背景：`docs/plans/2026-09-13-mypy-cleanup.md`（适度档清账收官，138→0）；本设计为下一档升级。

## 1. Problem Statement & User Value

**现状**：Mypy 门禁停在"适度严格"档（`check_untyped_defs` + `no_implicit_optional` + `warn_unused_ignores` + `warn_redundant_casts` + `ignore_missing_imports`，见 `pyproject.toml [tool.mypy]`）。该档**不检查无注解函数**（`no-untyped-def` 默认只给 note）——函数签名缺失类型意味着：

- 调用方失去类型推导锚点，`no-untyped-call` 在关键链路上静默放行；
- 重构/打包/跨端（Android pydantic 1.x 等）风险只能靠运行时爆炸暴露（v5.7.2 model_copy 事故先例：mypy 适度档拦不住 v2 专属 API 误用）。
- 发版节奏已到 5.9.2（三天四版），代码规模 53 个源文件 + 250 处 strict 错误，类型债持续累积的边际成本上升。

**价值**：`mypy --strict` 零错误 → 门禁覆盖全部无注解函数；无注解调用链在 CI 就被钉死；类型债清零后新增代码必须带注解（纪律自维持）。250 处实测比早先预估 ~600 轻，正是清账窗口。

## 2. 目标与验收（Definition of Done）

1. `python -m mypy --strict deletor` → **零错误**（250→0，53 源文件）。
2. ci.yml 门禁从裸 `mypy` 切换为 `mypy --strict deletor`（tests/tools 暂不 strict，另论）。
3. 全量 pytest 无回退（当前基线 **973 passed + 1 skipped**）；ruff 零告警不退化。
4. 全程**零运行时行为改动**：只补注解与显式 cast，不动逻辑；如 strict 暴露真实缺陷，按"缺陷修复"单独裁决（对齐 mypy-cleanup 先例：发现并修 2 处真实缺陷）。

## 3. 架构与清账策略（Architecture & Data Models）

### 3.1 错误分布（实测 `mypy --strict --no-error-summary deletor`）

| 模块 | 错误数 | 主因 |
|---|---|---|
| routes/main.py | 78 | no-untyped-def（~60）+ no-untyped-call 链 |
| core/database.py | 41 | no-untyped-def（db 层函数签名缺注解） |
| routes/encounter.py | 14 | no-untyped-def |
| core/lexicon.py | 13 | no-untyped-def |
| nlp_engine/linguistics.py | 10 | no-untyped-def + spaCy 占位交互 |
| routes/a1.py | 10 | no-untyped-def |
| routes/syntax_hard.py | 9 | no-untyped-def |
| data/lexicon_merge.py | 8 | no-untyped-def |
| server.py | 7 | no-untyped-def + load_env 无注解 |
| nlp_engine/processor.py | 7 | no-untyped-def |
| tools/vocab_stats.py | 6 | no-untyped-def |
| services/tts.py | 5 | no-untyped-def |
| 其余 19 文件 | ~42 | no-untyped-def 散点 |

Top 8 模块占 183/250（73%）。主体为**机械补注解**，按模块分批提交、每批可独立验证。

### 3.2 分阶段清账

- **Phase 1（核心热路径）**：`routes/main.py` + `core/database.py`（119 处）——含 no-untyped-call 连锁，工作量最大，先啃。
- **Phase 2（业务路由）**：`routes/encounter.py` + `routes/a1.py` + `routes/syntax_hard.py` + `core/lexicon.py` + `nlp_engine/linguistics.py`（56 处）。
- **Phase 3（其余）**：`data/lexicon_merge.py` + `server.py` + `nlp_engine/processor.py` + `tools/vocab_stats.py` + `services/tts.py` + 其余 19 文件（75 处）。
- **收口**：全仓 `mypy --strict deletor` 零错误 → ci.yml 门禁切换 → `docs/plans/` 执行状态回填 + work.log。

### 3.3 注解策略（Data Model）

- **返回值**：缺省一律显式 `-> None` 或推导类型；`-> Dict[str, Any]` / `-> List[Any]` 仅用于真实异构返回（与既有 ruff line-length=120 对齐）。
- **参数**：按实际消费补 `str` / `int` / `Optional[...]` / `Sequence[...]` 等；`**kwargs` 用 `Dict[str, Any]`。
- **`no-untyped-call` 连锁**：被调函数补完注解后，调用方若暴露类型不匹配 → 修正为正确类型（**不改运行时语义**）；确属隐式 Any 的中间层显式标注。
- **红线 1 豁免维持**：`nlp_engine/syntax_tree.py` 的 spaCy 降级占位（`Doc = Any` 等带理由 `# type: ignore[assignment]`）在 strict 下若报错，用带理由的 `# type: ignore[...]` 显式维持（**豁免不删理由**）。
- **数据字典文件**：`delector/data/*.py` 巨型字典型模块若 strict 报大体积错误，评估按 ruff E501 同款思路豁免（`# mypy: disable-error-code="no-untyped-def"` 于文件头部，带理由）——**优先真补，豁免仅作最后手段**。

## 4. 边界与韧性（Edge Cases & Resilience）

- **不过度设计**：不引入 `types-*` 第三方 stub 包（keep `ignore_missing_imports=true`）；不重构业务函数结构；不把补注解顺带改逻辑。
- **Pydantic 跨端**：Android 侧 pydantic 1.x 无 v2 API——补注解不得引入 `model_copy` 等 v2 专属调用（跨端打包守卫 `test_syntax_score_no_pydantic_v2_only_api` 会拦截，天然防线）。
- **批量提交粒度**：Phase 内按模块拆分提交，每个提交 `mypy --strict`（定向模块）+ pytest 局部跑通才推；**单提交失败可整体回滚**。
- **strict 暴露真实缺陷**：每处单独评估——修复 if 明确正确；不确定则记录 `docs/plans/` 留待人工裁决，不强行 ignore 掩盖。

## 5. 测试策略（Test Strategy）

- **门禁本身**：`mypy --strict deletor` 零错误作为验收（本地 + ci.yml 切换后 CI 强制）。
- **回归**：每 Phase 结束跑全量 `pytest -q`（基线 973+1 不回退）+ `ruff check .` 零告警。
- **守卫扩展**：`tests/test_ci_hardening.py` 若断言 mypy 档位/命令，同步更新（该守卫钉 ci.yml 反冻结集合）。
- **探针**：`tools/*.mjs` 前端探针不受影响（纯后端注解改动），全绿即可。

## 6. 不做（Scope Control）

- ❌ 不升级 tests/ 与 tools/ 至 strict（另立计划）。
- ❌ 不引第三方 stub 包、不改 `ignore_missing_imports`。
- ❌ 不借机重构/格式化/重命名。
- ❌ gloss 产包不在本计划内（DEEPSEEK_API_KEY 缺失，待 key 后另启）。

## 7. 决策记录（Pending）

| 决策点 | 候选 | 倾向 |
|---|---|---|
| ci.yml 门禁形态 | A) `mypy --strict deletor` B) 配置写入 pyproject 后裸 `mypy` | A（显式、与 tests/tools 范围隔离清晰）；待清账收口时定 |
| data/*.py 字典文件 | A) 真补注解 B) 文件头 disable-error-code | 优先 A，B 仅当体积/收益失衡 |
