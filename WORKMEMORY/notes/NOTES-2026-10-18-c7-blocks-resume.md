# C7 剩余工作接续笔记（2026-10-18）

> 用途：**替代对话上下文**。任何 agent 读这一页即可接续，不需要回溯会话。
> 位置：`WORKMEMORY/notes/`（超限事件正文目录）。

## 1. 当前状态（唯一真值）

| 项 | 值 |
| --- | --- |
| worktree | `d:\Code\DeLector-c7b` |
| 分支 | `refactor/c7-workbench-blocks`（已推送） |
| HEAD | `efd5e5c`（工作区**干净**） |
| 基线 | `0b5758b`（= PR #152 合并后的 master） |
| 未开 PR | 6 个提交攒在一起，**计划最后一次性开** |

## 2. 已完成（Task 5 的 5.5/6 块）

| 块 | 模块 | 声明 | 行数 | 备注 |
| --- | --- | --- | --- | --- |
| 1 tts-audio | `static/js/wb-tts.js` | 8 | 308 | `playWord` + 7 个 `_tts*` |
| 2 seed-persist | `static/js/wb-idb.js` | 16 | — | `loadAll` / `saveWords` / 整套 IDB |
| 3 render-views | `static/js/wb-views.js` | 9 | 386 | `renderStats`/`renderWords`/… |
| 4 wbsync | `static/js/wb-sync.js` | 4 段 | 499 | 含 `STARTUP_SEG`/`HYDRATE_SEG` 结构化 |
| 5 scope-filter | `static/js/wb-scope.js` | 10 | 147 | `SCOPE_PREDICATES`/`cefr*`/`wordState` |
| 6-1 队列构建 | `static/js/wb-queue.js` | 8 | 169 | `buildReviewQueue`/`injectWrongWords`/`refilter…`/`renormalize…`/`extraNewWords`/`extraPractice`/`queueInfoText`/`manualExtraIds` |

`static/german/workbench.html`：**4345 → 2984 行**（-31%）。入口路径未改名。

## 3. 唯一剩余步骤：6-2 队列渲染

**搬**：`renderReview` · `renderQuizQ` · `showCard` · `doRate` + 会话态
`revQueue` / `revIdx` / `flipped` / `ratedCount` / `queueDay`（模块对它们只有运行期引用）。

建议落到 `static/js/wb-queue.js`（同块合并）或新建 `wb-rate.js`（若独立更清晰）。
加载序：`seed-data → idb → tts → views → sync → scope → queue → 主内联脚本`。

## 4. 每块必须做到的（已验证有效的模板）

1. **字节等价**：每段 `sha256` 搬前 = 搬后（分段贴，不许抽样）。
2. **零行为漂移**：18 个 `tools/wb_*.mjs` 全 `exit 0`；`--json` 行为字段逐字相等（`wb_pair_persist` 仅墙钟 `ts`）。
3. **变异自证 ≥3**：改坏被搬代码 ⇒ 对应断言**必须**红 ⇒ 复原后 sha256 逐字节一致。
4. **用例数守恒**：**必须跑这 5 个文件**（160+ 用例）——
   `tests/test_german_workbench.py` · `test_frontend_module_graph.py` · `test_wb_source.py` · `test_workbench_tokens.py` · `test_audit_hardening.py`
   （前 3 个是 C7 自己的，后 2 个是**外围**——曾因只跑前 3 个漏掉两处真回归。）
5. **门禁**：`ruff check .` · `mypy --follow-imports=skip tests` · `mypy --strict delector tools` · 新文件 `lone_LF=0` · `node --check`。
6. 原子提交（`refactor(c7): …`），不直推 master。

## 5. 已知陷阱（血泪，务必照做）

1. **判别力只许升不许降**：搬迁类改动的标准做法是"**双向所有权钉子**"——`function <name>(` **必须不在** HTML、**必须在新模块**。这条已抓出两次真回归。
2. **跨文件锚点必须带前导换行**（`"\nconst wbsync = "`）：裸串会命中模块文件头注释里的示例，`decl_body` 切出注释占位 `{…}` ⇒ **断言变成对文档撒谎**。
3. **切片用 `decl_body`，不要用"切到下一个顶层 function"**：模块内居末的声明会因缺终止符而红（`extraNewWords` 踩过）。
4. **验证面 = 所有引用 `workbench.html` 的测试**，不是"本工作流的文件"。已漏过两次。
5. **`--extract` 是地雷**：`tools/build_workbench_seed.py --extract` 会把 `delector/data/a1_workbench_dict.py` 从 45 行**手工投影**覆盖成 764 行生成物（HEAD 既有行为）。**不要跑**；若要修，单独立项加 `--i-know-this-overwrites` 护栏。

## 6. 收尾清单（6-2 之后）

1. 全量 `pytest`（唯一一次；跑后贴 passed/skipped）。
2. 逐字复刻 CI：`mypy --strict delector tools` · `mypy --follow-imports=skip tests` · `ruff check .` · `cd agent && go test ./... -count=1 && gofmt -l .`。
3. 两条新闸：`python tools/check_mock_drift.py` · `python tools/check_silent_degradation.py`（均须 `exit 0`）。
4. 28 个改动文件的 CRLF `lone_LF=0`。
5. `WORKMEMORY/work.log` 追加 `DONE` 事件。
6. 开 PR（base=master），body 里写明：6 个块的模块清单 · 字节等价与变异自证 · 用例数守恒（只允许新增 `test_wb_source.py` 28 条）· 已知风险（`--extract` 地雷、`slices` 对结构敏感、5 个未接线探针的实际判定）。
