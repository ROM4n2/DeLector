---
title: "ADR-0009: Python 包内重构落点的 Deletion Test 修正与 Agent 工具契约语义"
created: 2026-09-06
updated: 2026-09-06
type: project
tags:
  - project/delector
  - topic/architecture
  - topic/refactoring
  - topic/tdd
status: stable
audience:
  - architect
source: ""
authority: synthetic
claim_risk: medium
review_status: unreviewed
---

# ADR-0009: Python 包内重构落点的 Deletion Test 修正与 Agent 工具契约语义

- **状态**: Accepted
- **日期**: 2026-09-06
- **作者**: Lead Socratic Inquisitor & Refactoring Specialist（vault-grill 双镜拷打）
- **领域**: Backend Architecture / Python Packaging / Agent Tool Contract
- **拷打对象**: Phase 1 包内重构 T5–T7 落地物（`docs/plans/2026-09-06-python-restructure-phase1.md`）

---

## 1. 背景与问题定义 (Context & Problem Statement)

Phase 1 重构（T1–T7）全量收官后，以「代码重构与精简师」视角对 T5–T7 产物做 frontline 拷打，
三条实测事实浮出水面：

1. **`services/__init__.py` 的 17 个符号级扁平 re-export 零消费方**：全部消费方
   （routes/×3、tests/×6）均直连子模块 `from delector.services.writing import ...`。
   无人使用的"便利入口" = 为未来可能预留 = YAGNI 违背；且与同一 session 刚沉淀的
   规则「子包 `__init__` 只收零依赖符号」（T6 `core/__init__` 已遵守）自相矛盾。
2. **`tools/exercise` 语义造假**：计划书写"练习生成"，实际包装的是
   `services.writing.analyze_a1_email`（**批改**）。错误名字的函数比缺失的函数更贵——
   它会诱导 Phase 2 的 Go Agent 与后续维护者按错误语义调用与扩展。
3. **`tools/export.py` 使用 `tempfile.mktemp()`**：官方废弃 API，存在 TOCTOU 竞态
   （返回文件名与真正创建之间可被抢注）。

## 2. 决策驱动因素 (Decision Drivers)

- **删除测试 (The Deletion Test)**：降低复杂度优先靠删——单消费方（此处零消费方）的
  入口层必须删。
- **天梯 Level 0 (User Value)**：`tools/` 的存在合法性不因"当前无调用方"被否——
  Phase 2 Go Agent 已在 ADR-0008 排期，T7 交付的是**HTTP 契约原型**，属已排期前置
  而非臆想需求；但单个 tool 的**语义必须真实**。
- **天梯 Level 1 (Stdlib)**：临时文件交给调用方显式指定，服务端拒绝自选落点；
  标准库废弃 API 禁止使用。
- **自洽性**：架构规则必须对 T5/T6/T7 一视同仁，不允许"自己定的规则自己破"。

## 3. 备选方案考量 (Considered Options)

- **Q1 services 扁平 re-export**：
  - *Option B 保留现状*（plan 契约优先，留作 Phase 2 缓冲）——*否决*：零调用方入口
    是臆想需求；Phase 2 需要时加回仅需 5 分钟。
  - *Option A 改 core 模式* [选中]：`__init__` 只 re-export 4 个模块对象，
    `__all__ = ["essay_diff", "exam_catalog", "tts", "writing"]`，docstring 写明
    消费方直连子模块。
- **Q2 tools 层**：
  - *Option B 激进精简*（只留 ingest/tts，删 3 个无调用方 tool）——*否决*：契约原型
    是已排期交付物，删除会造成 Phase 2 开工时契约重搭。
  - *Option A 最小修正* [选中]：`exercise` → `writing_check`（注册键同步更名），
    真正的"练习生成"出现时另立 tool；`export` 的 `output_path` 改必填，缺失即
    `ValueError`（路由层转 400），彻底移除 `tempfile.mktemp` 兜底。

## 4. 架构决策 (Decision Outcome)

1. `delector/services/__init__.py` 采用 **core 模式**：仅模块对象 re-export + 对齐
   `__all__`，符号级扁平入口删除（commit `f900fe4`）。消费方契约不变。
2. `delector/tools/exercise.py` 更名 **`writing_check.py`**，`TOOL_REGISTRY` 键
   `"exercise"` → `"writing_check"`（commit `b14a938`）。
3. `delector/tools/export.py`：`output_path` 必填，删除临时路径兜底。
4. ADR 独立编号（0009），不并入 ADR-0008（Go Agent Runtime 是运行时架构决策，
   本 ADR 是重构纪律与契约语义决策，主题不同）。

## 5. 后果与防御性规范 (Consequences & Defensive Rules)

- **子包 `__init__.py` 准入**：只 re-export 模块对象或零依赖符号；任何符号级扁平
  入口必须有真实调用方（≥1），否则删。预期中的"未来消费方"不构成准入理由。
- **Tool 命名 = 语义**：tool 名必须精确描述被包装能力的真实语义（批改 ≠ 生成）；
  语义漂移时宁可更名，不可将错就错。
- **服务端禁止自选持久化落点**：任何"输出路径"参数一律必填；临时路径兜底
  （`mktemp` 类）禁止出现在服务端代码。
- **plan 契约条款让位于实测**：接口契约（如"`__init__` 必须定义 `__all__`"）在
  Deletion Test 面前可修订，修订须回写 plan 文档并归档 ADR。
- 已知残留：`delector.services` 包级 import 仍会经 `__init__` 拉起 4 模块（含
  exam_catalog→spaCy 链）；当前无"spaCy 空载场景"的独立消费者，PEP 562 惰性化
  按 YAGNI 暂缓，若 Phase 2 出现该场景再启用。
