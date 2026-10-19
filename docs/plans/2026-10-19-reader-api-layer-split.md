# Reader.js L2 持久化层抽离 (`rd-api.js`) 与前端分层机械闸纳管面扩展实施计划

> **规范依据**：`dfs-plan` / `dfs-exec` / `monolith-split-readiness` / `mechanical-gate-authoring`
> **基线分支**：`refactor/reader-api-layer-split` (自 master `496bef7` 切出)
> **目标**：
> 1. 将 `static/js/reader.js` 内部 18 处 `api()` 访问抽离出独立的 L2 持久化访问层 `static/js/rd-api.js`。
> 2. `reader.js` 内部调用改为使用导入名，保持 40 个对外具名导出绝对冻结，所有 `notify/alert/console.error` 错误轨进出完全保真。
> 3. 扩展前端分层机械闸 `tools/check_frontend_layers.py`：
>    - 注册 `rd-api.js` 为 L2 持久化层（禁 DOM、禁弹窗、禁定时器、禁顶层可变状态）。
>    - 通用化规则⑤（调用一致性）：将对 `wr-api.js` 的硬编码检查扩展为遍历所有 L2 模块。
>    - 将存量无 DOM、无网络的纯逻辑工具模块 `wb-queue.js`、`wb-scope.js` 正式纳入 L1 纯层声明。

---

## 📐 Global Constraints

- **零破坏性（FROZEN SURFACES）**：
  - `reader.js` 对外具名导出必须保持 **40** 个逐字不变。
  - 错误轨保真：`notify(` / `alert(` / `console.error(` 行内容进出相等（0 丢失，0 新增）。
- **分层契约（L2 CONTRACT）**：
  - `rd-api.js` MUST NOT 触碰 DOM（`document` / `window` / `innerHTML` 等）。
  - `rd-api.js` MUST NOT 弹用户提示（`notify` / `alert`）。
  - `rd-api.js` MUST NOT 用定时器（`setTimeout` / `setInterval`）。
  - `rd-api.js` MUST NOT 有顶层 `let`/`var`。
  - `rd-api.js` 唯一允许的 import 仅限 `./core.js` 的 `api`。
- **文件编码契约**：全仓文本必须 100% UTF-8 CRLF（0 lone LF）。

---

## 🎯 任务分解 (Task Breakdown)

### Task 1: 分层机械闸扩充（Gate-as-Spec先行，RED first） [Tier: 2-Standard]
- **文件**：
  - Modify: `tools/check_frontend_layers.py`
  - Modify: `tests/test_frontend_layers.py`
- **目标**：
  - 在 `LAYER_SPEC` 中注册 `rd-api.js`（L2 持久化层）、`wb-queue.js`（L1 纯层）、`wb-scope.js`（L1 纯层）。
  - 规则⑤（调用一致性 `check_api_call_consistency`）泛化为对所有 L2 模块有效。
  - 触发预期的 RED 凭据（`static/js/rd-api.js:1:missing-layer-module`，exit 1）。
  - 新增针对 `rd-api.js`、`wb-queue.js`、`wb-scope.js` 的红绿变异用例。

### Task 2: 抽出 `static/js/rd-api.js`（L2 独立持久化层） [Tier: 2-Standard]
- **文件**：
  - Create: `static/js/rd-api.js`
- **目标**：
  - 实现 12 个端点纯异步调用函数：
    1. `deleteArticleRemote(id)`: `DELETE /api/articles/{id}`
    2. `fetchArticlesRemote()`: `GET /api/articles`
    3. `fetchArticleRemote(id)`: `GET /api/articles/{id}`
    4. `lookupVocabRemote(payload)`: `POST /api/lookup/vocab`
    5. `lookupGrammarRemote(payload)`: `POST /api/lookup/grammar`
    6. `saveVocabCardRemote(payload)`: `POST /api/cards/vocab`
    7. `saveGrammarCardRemote(payload)`: `POST /api/cards/grammar`
    8. `fetchCardCountsRemote()`: `GET /api/cards/counts`
    9. `fetchArticleNotesRemote(articleId)`: `GET /api/articles/{articleId}/notes`
    10. `saveArticleNoteRemote(articleId, payload)`: `POST /api/articles/{articleId}/notes`
    11. `deleteArticleNoteRemote(noteId)`: `DELETE /api/notes/{noteId}`
    12. `aiNoteAssistRemote(payload)`: `POST /api/ai/note-assist`
    13. `saveSyntaxStatsRemote(payload)`: `POST /api/syntax/stats`
    14. `fetchSyntaxStatsRemote()`: `GET /api/syntax/stats`
  - `python3 tools/check_frontend_layers.py` 转绿（exit 0）。
  - `node --check` 语法与 ESM 导入验证。

### Task 3: `reader.js` 内部改向接线与导出面冻结 [Tier: 2-Standard]
- **文件**：
  - Modify: `static/js/reader.js`
- **目标**：
  - 导入 `rd-api.js` 中的 14 个远程调用函数。
  - 替换 18 处 `await api(` 调用点为对应函数。
  - 导出面冻结核验（40 == 40）。
  - 错误轨保真核验（10/10 集合完全守恒）。
  - `tools/cards_count_probe.mjs` 转换器及相关探针兼容性核验。

### Task 4: 独立可用性与测试套件适配 [Tier: 2-Standard]
- **文件**：
  - Create: `tests/test_reader_api_split.py`
  - Modify: 相关探针（若有耦合断言）
- **目标**：
  - 编写 `tests/test_reader_api_split.py` 验证 `rd-api.js` 独立可用性与闭包属性。
  - 变异自证（注入 DOM / toast / timer 必须报出规则名并退出码 1）。

### Task 5: 全量门禁复核与 PR 交付 [Tier: 1-Light]
- **目标**：
  - 六道 Python 机械闸全绿。
  - `ruff` / `mypy` / `go test` 全绿。
  - 全量 pytest 串行分批全绿。
  - CRLF 0 lone LF 检查。
  - `WORKMEMORY/work.log` 记账与创建 PR。
