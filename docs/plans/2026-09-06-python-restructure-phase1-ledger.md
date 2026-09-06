# Ledger — DeLector Python Restructure Phase 1

> Plan: `docs/plans/2026-09-06-python-restructure-phase1.md`
> Spec: `docs/specs/2026-09-06-adr-0008-go-agent-runtime-architecture.md`
> Created: 2026-09-06

## 执行方式（如实注明）

本环境**无写码子代理**（`task` 仅只读 code-explorer，`scripts/vault_exec_state.py` 不存在），
按项目既有降级约定（见 Stage B ledger）：**编排者主线程直写 + TDD 纪律 + 每 Task 原子提交**，
未伪造子代理。审核 = 每 Task 提交前定向测试 + 提交后全量回归。

## 基线

- 收包完成态（`e489f82`），工作区干净。
- 全量基线：修复收尾后预期 **585 passed + 1 skipped**（583 曾绿 + 2 修复定向绿；精确统计曾被 safe-delete 守卫吞行）。
- 红线：PROJECT_OVERVIEW 速查 11 条；尤其 #2 StaticFiles mount 必须最后、#9 import 期不得联网/抛异常。

## 执行记录

| Task | 标题 | 状态 | Commit | 验证 |
|---|---|---|---|---|
| T1 | 消除 Hazard：utils.py + 修跨边界 | ✅ `6f5fe67` | 全量 584 passed + 1 skip（守卫迁移定向修复） |
| T2 | 数据层 → `data/` | ✅ `5ba8204` + `1b7b478` | 全量 **585 passed + 1 skipped**（1b7b478 修打包注册断言旧路径后复跑全绿） |
| T3 | NLP 层 → `nlp_engine/` | ✅（本 commit） | 全量 585 passed + 1 skipped |
| T4 | 路由拆分 + server 瘦身 |  |  |  |
| T5 | 服务层 → `services/` |  |  |  |
| T6 | 基础设施 → `core/` |  |  |  |
| T7 | Agent 工具接口 `tools/` |  |  |  |

## T2 执行说明与偏离（2026-09-06）

- **偏离：只加 `data/` 层级、不改文件名**（原计划 core_dict→core.py、a1_dict→a1.py）。
  理由：最小 diff + 避免改名引用爆炸 + 与收包「保名只加包层」风格一致。`delector/data/` 下仍为
  a1_dict/core_dict/… 原名。
- import 迁移共覆盖 **4 种词法**（此前多次漏改/误拼 `delector` 教训）：绝对 dotted
  `delector.X_dict`、绝对绑定 `from deletor import X_dict`、相对绑定 `from . import X_dict`、
  相对 dotted `from .X_dict`。以程序推导包名脚本幂等迁移，未留旧路径引用（残留扫描 0）。
- **data 内部绝对引用需同步**：`data/core_dict.py` 底部的
  `from deletor.core_dict_ext import CORE_VOCAB_EXT`（try/except 包裹）若漏改，ImportError 被吞、
  CORE_VOCAB_DB 回落 443 条 → `test_core_dict_ext`/`test_dict_pipeline` 红。已改
  `delector.data.core_dict_ext`，合并后 CORE_VOCAB_DB = 4411。
- 打包清单同步：package_windows.py + build-release.yml 的 hidden-imports 全部 8 个词典统一改为
  `delector.data.<mod>`（8 个本都在 hidden-imports，含 a1_hoeren/lesen/writing——全量时
  `test_all_backend_modules_registered_in_all_packaging_targets` 抓出断言仍为旧形态，已随
  `1b7b478` 改为按 data 子包动态拼前缀）；Android 已 cp -r 整目录。
- 测试中 `test_goethe_a1_*`/`test_exam_catalog` 组合跑失败系已知「模块级 os.environ 污染」，
  单模块全绿，与搬迁无关。
- **待办：全量回归**（两次被用户跳过）；Task 3 前需补跑确认。

## T3 执行说明与偏离（2026-09-06）

- 按计划 rename：`nlp.py → nlp_engine/processor.py`（其余 syntax_tree.py / linguistics.py 保名）。
- 路径映射：`delector.nlp → deletor.nlp_engine.processor`；`delector.syntax_tree /
  .linguistics → deletor.nlp_engine.*`。consumer 迁移 26 处 import（AST 枚举兜底，含
  server/database/essay_diff/writing_rules + 10 个 test/tools 文件）。绑定形态改写：
  `from deletor import nlp` → `from deletor.nlp_engine import processor as nlp`（测试里
  以 `nlp._load_spacy_model` 等内部名使用，目标模块保留同名符号即可）。
- `nlp_engine/__init__.py` re-export 17 个公开名（processor 3 + syntax_tree 6 + linguistics 8）。
- **踩坑①（迁移脚本自身）**：替换函数里 value 已是全路径又再拼 `nlp_engine.` 前缀 →
  双份 `nlp_engine.nlp_engine`；先 `git restore` 消费方再跑修正脚本。nlp 组应映射
  processor 而非透传 `nlp`（曾短暂产生 `nlp_engine.nlp`）。
- **踩坑②（历史复犯）**：把包名拼成 `deletor`（漏 c）——processor.py:13 手写
  import 落成 `from deletor.utils import`，collection 报 `No module named 'deletor'`。
  修正后 586 收集干净。规则：别手打包名，脚本用 `'dele'+'ctor'` 拼接。
- 静态源码测试 3 例读旧路径 `delector/nlp.py` → 改指 `delector/nlp_engine/processor.py`。
- 全量证据：首轮 3 failed（静态路径），修复后 **585 passed + 1 skipped**。
