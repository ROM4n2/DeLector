---
title: "ADR-0013: 词汇富字段输出契约扩展（A2/B1 音标与例句下发）"
created: 2026-09-16
updated: 2026-09-16
type: project
tags:
  - project/delector
  - topic/architecture
  - topic/api-contract
  - topic/data-model
status: stable
audience:
  - architect
  - developer
source: "ADR-0012 §5-2 预留的扩展路径 + 用户交付 official_vocab_rich.py 检验（vault-plan 收口后接续）"
authority: synthetic
claim_risk: medium
review_status: unreviewed
---

# ADR-0013: 词汇富字段输出契约扩展（A2/B1 音标与例句下发）

- **状态**: Accepted
- **日期**: 2026-09-16
- **领域**: 服务端输出契约 / 前端卡片 / 数据分层
- **上游**: ADR-0011（9 字段契约冻结 / 5 元组存储冻结）、ADR-0012（主干分层 + §5-2「扩展字段须另立 ADR」）
- **落地计划**: `docs/plans/2026-09-15-goethe-official-vocab-migration.md` §10（Phase 2）

---

## 1. 背景与问题定义 (Context & Problem Statement)

### 1.1 现状
- **A2/B1 卡片没有任何富字段**（ADR-0011 §1.2-P2 遗留）：`contract` 的 `de` 恒为空串，前端 `a1_cards.js::mapCardsVocabItem` 的 `example_zh` **硬编码 `""`**，workbench `syncB1CardsFromServer` 的 `ipa` **硬编码 `""`**、`syncA2CardsFromServer` 读 `rw.ipa`（服务端未下发）。
- **A1 已有富数据**：`a1_workbench_dict.A1_WORKBENCH_SEED`（682，`ipa` + `ex:[{de,zh}]` 全覆盖）、`a1_dict.GOETHE_A1_VOCAB`（702，`example_de`/`example_zh` 全覆盖）。→ 三级卡片信息量不对等。
- **新交付物**：用户 + 外部 agent 产出 `official_vocab_rich.py`（`lemma -> {ipa, example_de, example_zh, topic}`），实测 **A2 736 / B1 1617 = 100% join 覆盖、零多余键**；IPA 由规则 g2p 生成（源 `ipa_map.json`），例句德文取自官方 PDF、中文逐字取自源文件（非机翻）。

### 1.2 问题
- **P1 契约冻结挡住下发**：`tests/test_vocab_contract_uniform.py` 以 `set(w.keys()) == CONTRACT_FIELDS`（**严格相等**）钉死 9 字段 `{id,hw,pos,gender,plural,de,zh,core,cefr}`；无 `ipa` / 中文例句位。ADR-0012 §5-2 已预留"扩展须另立 ADR"路径。
- **P2 前端缺位**：`a1_cards.js` 无中文例句字段可用；workbench A2/B1 档无音标。
- **P3 IPA 表示法不一致**：rich 用 tie-bar（`t͡s`/`p͡f`/`t͡ʃ`，252 条），现有 A1 主流用 `ts`/`pf`/`tʃ`（seed 内还残留 4 条 `t͡s`）。
- **P4 A1 例句缺口**：rich 的 A1 `example_zh` 仅 198/660（外部源覆盖不足），但项目内部数据可补到 640/660。

## 2. 决策驱动因素 (Decision Drivers)

- **信息量对齐**：A1 已有音标+例句，A2/B1 应对齐（备考域卡片背面 + 工作台词表）。
- **不破存储冻结**：富字段是**输出层 side-car**，绝不进 5 元组存储（ADR-0011 §5-6 / ADR-0012 §5-1）。
- **一次取全**：避免前端二跳端点与两处形状漂移。
- **可测守线**：契约字段集变更必须有守卫测试同步（不许静默放宽）。
- **可重放**：IPA/例句的生成链须可追溯（源文件 + 生成脚本）。

## 3. 备选方案 (Considered Options)

- **Option A（选定）：扩展 `/api/cards/vocab` 契约 +2 字段**
  - 👍 前端一次取全；与 A1 语义一致（`de` 已是"德语例句"位）；改动集中。
  - 👎 破 9 字段冻结 → 必须同步契约守卫 + 探针 + 前端映射。
- **Option B：新增独立端点 `/api/cards/vocab/rich`**
  - 👍 现有契约零改动。
  - 👎 前端二跳 + 缓存一致性 + 同一条目两处形状漂移（长期维护面更大）。

## 4. 决策 (Decision Outcome)

**选定 Option A。**

1. **契约扩展为 11 字段**：`{id, hw, pos, gender, plural, de, zh, ipa, example_zh, core, cefr}`。
   - `de` 语义统一为**德语例句**（A1 取 `ex[0].de`，A2/B1 取 rich 的 `example_de`）。
   - 新增 `ipa`（音标）与 `example_zh`（例句中文）。
   - 唯一产出点仍是 `_contract_item`（ADR-0012 §5-1 延续）。
2. **富字段来源**：新增数据分片 `delector/data/official_vocab_rich.py`（纯数据、零副作用）；主干 `lexicon.rich_of(lemma)` 提供查询（`RICH` 加载期建索引）。
3. **A1 不切 rich**：`A1_WORKBENCH_SEED` / `GOETHE_A1_VOCAB` 已全覆盖；rich 的 A1 与现有差异**仅为表示法**。A1 分支保持原值（该缺口用内部数据补，见 §6-S3）。
4. **IPA 表示法统一**：**去除 tie-bar（U+0361）**，使 `t͡s→ts`、`p͡f→pf`、`t͡ʃ→tʃ`，与现有 A1 主流一致（252 条受影响）。
5. **前端接线**：`a1_cards.js` 的 `example_zh` 接真值；workbench A2/B1 档填 `ipa`，`ex` 形状统一为 `[{de, zh}]`（与 A1 seed 一致）。
6. **空值策略**：rich 缺字段 → **显式空串**，禁止编造或静默降级（红线 2 精神）。

**明确不做（scope 控制）**：不改 A1 的 IPA 来源（不引入 rich 的 A1）；不改 5 元组存储；不新增端点；不动 `A1_WORKBENCH_SEED` / `GOETHE_A1_VOCAB` 的派生收敛（ADR-0012 Phase 2 的另一支，另议）。

## 5. 后果与防御性规范 (Consequences & Defensive Rules)

🟢 **正面**：三级卡片信息量对齐；A2/B1 首次具备音标 + 双语例句；备考域/工作台同一份富字段（单一来源）。
🔴 **代价**：破 9 字段冻结（须同步 `tests/test_vocab_contract_uniform.py` + `tools/wb_*_probe.mjs`）；前端改动 → **Android 需覆盖安装**；rich 为空字段处保持空串显示。

**防御性规范（MUST）**
1. **5 元组存储冻结不破**：富字段只在输出层（`_contract_item` / `lexicon.rich_of`），禁止写入数据模块的 5 元组或 SQLite。
2. **契约字段集唯一**：由 `_contract_item` 单点产出 11 字段；守卫测试同步为 11 字段（严格相等，不得放宽为子集断言）。
3. **禁止编造**：rich 缺值 → 空串；不得用 AI/规则临时补造句。
4. **IPA 表示法唯一**：全局无 tie-bar（U+0361）；由测试/探针钉住（含 rich 分片与下发链路）。
5. **单入口**：消费端只经 `lexicon`（ADR-0012 §5-3 延续），禁直连 `official_vocab_rich`。
6. **打包三处同步**：新数据模块 `delector.data.official_vocab_rich` MUST 同步 `package_windows.py` / `build-release.yml` / `tests/test_server.py::data_dict_modules`。
7. **可重放**：`gen_rich.py`（或等价生成脚本）MUST 归档进 `tools/`；rich 分片头注写明来源与生成方式。

## 6. 实施顺序（S1–S6，供 /vault-exec）

1. **S1** 富字段分片入库：`delector/data/official_vocab_rich.py`（含 IPA 去 tie-bar 归一化）+ 源校验测试。
2. **S2** 主干视图：`lexicon.rich_of(lemma)` + `RICH` 索引 + 测试（覆盖/缺值/确定性）。
3. **S3** A1 中文例句补齐：用 `A1_WORKBENCH_SEED.ex[0].zh` / `GOETHE_A1_VOCAB.example_zh` 回填 A1 分支的 `example_zh`（198→640 的可补面）。
4. **S4** 契约扩展：`_contract_item` 9→11 字段；A1/A2/B1 三分支填值；同步 `tests/test_vocab_contract_uniform.py`。
5. **S5** 消费端接线：`/api/a2/vocab` 下发 `ipa`；workbench A2/B1 档（`ipa` + `ex:[{de,zh}]`）；`a1_cards.js::mapCardsVocabItem` 接 `example_zh`；同步 `tools/wb_cards_vocab_unwrap_probe.mjs` 等探针。
6. **S6** QA 与收口：产出 IPA 人工复核清单（10 条空 IPA + artifacts 抽样）；`PROJECT_OVERVIEW` / 计划执行状态回填；全量门禁。

## 7. 相关 (References)

- **上游**：ADR-0011（9 字段契约 / 5 元组冻结 / A1 富字段现状）、ADR-0012（主干分层 / §5-2 扩展路径 / §5-3 单入口）。
- **交付物检验**：`docs/plans/2026-09-15-goethe-official-vocab-migration.md` §10（覆盖度 100%、A1 缺口、IPA artifacts）。
- **取证**：`delector/core/database.py`（`_contract_item` / `_contract_from_core_entry` / `_load_a1_workbench_words`）、`delector/routes/a2.py`、`static/js/a1_cards.js::mapCardsVocabItem`、`static/german/workbench.html::syncA2CardsFromServer/syncB1CardsFromServer`、`tests/test_vocab_contract_uniform.py`。
