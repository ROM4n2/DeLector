# Mypy Strict 清账执行计划（2026-09-18）

> 设计见 `docs/specs/2026-09-18-mypy-strict-annotation-sweep-design.md`（已批准）。
> 状态：Phase 1 in progress。基线：973 passed + 1 skipped / 250 strict errors / 31 files。

## 任务分解

- **Phase 1（核心热路径，119 处）**：
  - T1 `routes/main.py`（78）
  - T2 `core/database.py`（41）
- **Phase 2（业务路由，56 处）**：
  - T3 `routes/encounter.py`（14）+ `routes/syntax_hard.py`（9）
  - T4 `routes/a1.py`（10）+ `core/lexicon.py`（13）+ `nlp_engine/linguistics.py`（10）
- **Phase 3（其余，75 处）**：
  - T5 `data/lexicon_merge.py`（8）+ `server.py`（7）+ `nlp_engine/processor.py`（7）+ `tools/vocab_stats.py`（6）+ `services/tts.py`（5）
  - T6 其余 19 文件（~42）
- **收口 T7**：全仓 `mypy --strict deletor` 零错误 → ci.yml 门禁切换（决策记录 A）→ 执行状态回填 + work.log

## 纪律（每任务强制）

1. **只补注解**：`-> None` / 推导类型 / 显式 `Dict[str, Any]`；不重构、不改逻辑、不重命名。
2. 验收：`mypy --strict --follow-imports=skip <file>` 零错误 + `pytest tests/<相关模块>` 局部回归。
3. 严禁引入 pydantic v2 专属 API（跨端守卫拦截）；红线 1 豁免 `# type: ignore[...]` 带理由维持。
4. strict 暴露真实缺陷 → 修复 if 明确正确；不确定记录本文件，不 ignore 掩盖。

## 状态（2026-09-18 收官）

| 任务 | 文件 | 状态 |
|---|---|---|
| T1 | routes/main.py | ✅ done（62 处 + 模块级 disable misc/untyped-decorator） |
| T2 | core/database.py | ✅ done（24 处 + 9 ignore） |
| T3 | encounter + syntax_hard | ✅ done（20 处；skip 模式 ignore 在默认模式下已删） |
| T4 | a1 + lexicon + linguistics | ✅ done（31 处；lexicon 补 re-export as 语法） |
| T5 | lexicon_merge + server + processor + vocab_stats + tts | ✅ done（29 处；processor 红线 1 占位恢复带理由 ignore） |
| T6 | 其余 19 文件 | ✅ done（47 处） |
| T7 | 全仓验收 + 门禁切换 | ✅ done：`mypy --strict deletor` 零错误（250→0）；全量 pytest **989 passed + 1 skipped**；ruff 零告警；ci.yml 门禁切 `mypy --strict deletor` |

收口明细：`test_official_vocab.py` 纯数据守卫冻结集合加入 Optional/Tuple（typing 类型对象白名单扩展）；`main.py:509` groups 显式 `List[Dict[str, Any]]`。
