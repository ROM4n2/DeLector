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
| T2 | 数据层 → `data/` | ✅（本 commit） | 定向 49 passed（字典/布局/算法/导入链）+ 收集 586 clean；全量待跑（用户跳过） |
| T3 | NLP 层 → `nlp_engine/` |  |  |  |
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
- 打包清单同步：package_windows.py + build-release.yml 的 hidden-imports 改为
  `delector.data.{core_dict,core_dict_ext,prep_dict,a1_dict,corpus_dict}`（a1_hoeren/lesen/writing
  本就不在 hidden-imports；Android 已 cp -r 整目录）。
- 测试中 `test_goethe_a1_*`/`test_exam_catalog` 组合跑失败系已知「模块级 os.environ 污染」，
  单模块全绿，与搬迁无关。
- **待办：全量回归**（两次被用户跳过）；Task 3 前需补跑确认。
