# rd-api.js 导出面守卫：对抗性复核（GUARDS BROKEN）

> **状态：已闭环。** 本报告记录的是 `33ab4c6` 时点的事实 —— 两条守卫当时确实被
> 打破。报告结论中的两类逃脱（字符串导出名 / `default` 导出）已在 `c8acff2` 修掉，
> 随后又补出「解构导出」一类，最终判据在 `f2bdb73` 从**静态语法枚举**改为
> **运行时真值**（node 真正 import 后数 `Object.keys()`），静态解析降级为
> 「不许漏报」的辅助断言。六种已知形态重放全部 CAUGHT。
> 相关计划：`docs/plans/archive/2026-10-19-reader-api-layer-split.md`（第三、四轮评审节）。
> **保留本报告的理由**：它同时是「守卫被同类手法连穿两次」的一手证据，
> 以及一份 15 行的语法形态清单 —— 后来者写导出面守卫时应当直接对照。

- 目标：`33ab4c6 fix(rd): parse the export surface from tokens, not column-0 regexes`
- 被测：`tests/test_reader_api_split.py::test_rd_api_export_surface_is_exactly_the_endpoints`
  与 `::test_rd_api_has_no_dead_exports`
- 方式：在 `git archive 33ab4c6` 的副本上逐条注入，跑
  `pytest -k "export_surface or dead_exports"`、`tools/check_frontend_layers.py`、`node --check`
- 干净树上：`14 passed`，闸 `exit 0`（无假阳性）

## 结论

token 级解析修好了「`as` 右边才是导出名」和「行首缩进」两个洞，但 `_exported_names()`
仍有两类**合法 ESM 语法**完全不可见，且守卫、闸、`node --check` 三者同时保持绿色：

1. **字符串导出名** `export { removeArticle as "deleteArticleRemote" };`（ES2022 任意模块命名空间名）
   —— `{...}` 分支取 `ids`，字符串 token 被丢弃，`ids = [removeArticle, as]` 长度 < 3，
   于是**回落到本地名** `removeArticle`（已在 14 名内），导出名 `"deleteArticleRemote"` 隐形。
2. **default 导出** `export default ...` —— `export` 后紧跟 id `default`，不匹配
   `function|const|let|var|class`，也不匹配 `{` / `*`，**没有任何分支记录它**，直接被 `continue` 漏过。

现场证据（14 个别名全部改成字符串名后）：

```
pytest export_surface+dead_exports: 2 passed
check_frontend_layers.py:          exit 0
node --check:                      exit 0
node "import * as ns":             export-count: 28
runtime import { "deleteArticleRemote" as x }: function
```

即：原缺陷的 28 个导出**完整复活**，两条守卫全绿。

## 逐条结果

| # | 手法 | pytest | gate | node --check | 判定 |
|---|------|--------|------|--------------|------|
| A1 | `export { removeArticle as deleteArticleRemote };` | 1 | 0 | 0 | CAUGHT |
| A2 | 行首缩进的 `export { ... as ... }` 块 | 1 | 0 | 0 | CAUGHT |
| A3 | `export { removeArticle as "deleteArticleRemote" };` | 0 | 0 | 0 | **ESCAPED** |
| A4 | `export * from './core.js';` | 1 | 0 | 0 | CAUGHT（`extra: ['*']`） |
| A5 | 同一物理行两个 `export const` 别名 | 1 | 0 | 0 | CAUGHT |
| A6 | 别名被 reader.js 真 import（死导出守卫失明） | 1 | 0 | 0 | CAUGHT（导出面守卫独立兜住） |
| A7 | `export { removeArticle as removeArticle };` 自别名 | 0 | 0 | 1 | 守卫无误报；node 判 `Duplicate export`（合法地红） |
| A8 | 同名重复导出（local 重复声明） | 0 | 0 | 1 | 守卫无误报；node 判 `Identifier ... already declared` |
| B1 | `export default function deleteArticleRemote(){}` | 0 | 0 | 0 | **ESCAPED** |
| B2 | `export { removeArticle as default };` | 1 | 0 | 0 | CAUGHT（`extra: ['default']`） |
| B3 | `export default { deleteArticleRemote: removeArticle };` | 0 | 0 | 0 | **ESCAPED** |
| B4 | `export /* gap */ { a as b };` | 1 | 0 | 0 | CAUGHT（注释被丢弃） |
| B5 | `export { removeArticle as deleteArticleRemot\u0065 };` | 1 | 0 | 0 | CAUGHT（名字被截断，仍判红） |
| B6 | `export * as ns from './core.js';` | 1 | 0 | 0 | CAUGHT |
| B7 | 字符串导出 + reader.js 用字符串名真 import | 0 | 0 | 0 | **ESCAPED** |

CAUGHT 用例的断言原文：

```
AssertionError: rd-api.js export surface drifted.
  missing: []
  extra:   ['deleteArticleRemote', 'fetchArticlesRemote']
AssertionError: rd-api.js has dead exports (nobody imports them): ['deleteArticleRemote', 'fetchArticlesRemote']
```

## 建议修法（`tests/test_reader_api_split.py::_exported_names`）

```python
# { ... } 分支：取 `as` 后的 token，无论 id 还是 str
for it in items:
    names_ = [x[1] for x in it if x[0] in ("id", "str")]
    if not names_:
        continue
    if len(names_) >= 3 and names_[1] == "as":
        names.add(names_[2])          # 字符串名按原样（去引号）记入
    else:
        names.add(names_[0])

# 新增 default 分支：export default ...
if toks[j].kind == "id" and toks[j].text == "default":
    names.add("default")
```

另外，`export { a as "b" }` 的字符串名与 `default` 一旦进入 `exported`，
`exported <= declared` 这条交叉校验会因 `declared` 无同名而红 —— 需要把 `default`
与字符串名从该子断言中排除（或在 `EXPECTED_ENDPOINTS` 之外单列「禁止项」断言）。

复现脚本见同目录 `rd-api-export-guard-escape.harness.py` / `.proof.py`（对副本运行，未改 tracked 文件）。
