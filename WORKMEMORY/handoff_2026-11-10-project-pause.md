---
to: any
from: tencent-hunyuan-hy__codebuddy
created: 2026-11-10 22:04
role: IMPLEMENT | REVIEW | VERIFY
status: open
---
# Handoff: v5.23.0 发版收尾与项目阶段性暂停

## 任务上下文

DeLector（德语精读 / 歌德 A1–C1 与 TestDaF / DSH 备考的本地优先工作台）在 2026-11-10 完成 **v5.23.0** 发版后**阶段性暂停**，短期内不再推进。

- `master` = `72d6e7a`（`Merge pull request #339 from ROM4n2/release/v5.23.0`），与 `origin/master` 同步，工作树干净。
- 最新 tag = `v5.23.0`（annotated，指向 `72d6e7a`）；GitHub Release 已发布，四平台资产齐全。
- 版本面五件套 = `5.23.0` / `versionCode 52300`，由 `test_version_is_consistent_across_release_surfaces` 与 `test_app_version_source.py` 钉住。
- 发布文档规范自本版起生效：`CHANGELOG.md` 顶部 FORMAT RULES + `tools/check_release_docs.py` + `tests/test_release_docs_gate.py`（unit-2）。

## 已完成（含证据）

1. **v5.23.0 发版**：tag `v5.23.0` annotated 指向 `72d6e7a`；`build-release.yml` run `42829293169` success（5/5 job，4m4s）；资产 `DeLector-v5.23.0-{Windows-x64-Portable.zip, macOS.tar.gz, Linux-x64.tar.gz, Android.apk}` 均非零；Release 正文按 `.github/release-notes-template.md` 整份覆盖写入（无 emoji，新增/修复/内部/文档 + 已知限制 + 回滚四轴）。
2. **发布文档规范化（#338）**：修掉「规程写升序、CHANGELOG 实际降序」的根因；15 个版本头统一 `## vX.Y.Z - YYYY-MM-DD`、版本间 `---`、已知限制/回滚升级为 `###`；README 版本表钉住 ≤3 行；新增机械守卫与 10 例测试（真实树基线 + 8 类变异自证）。
3. **词卡写入幂等修复链（#332~#337）**：伴学落卡 `BEGIN IMMEDIATE` 事务边界（`commit=False`）、空 lemma 行级 UDF 同源回退（`card_identity` / `card_lemma_key`）、响应体 `created` / `skipped_fields`、5 个前端入口反馈语义、App 内「已知限制」本地说明。
4. **工作区清理**：临时 worktree 与已合并分支已删；保留 `release/v5.22.0`、`release/v5.22.1`、`release/v5.23.0` 作为回滚锚点（权威锚点是 `v*` annotated tag）。

## 未完成 / 下一步

1. **Android 真机点检**（宣传开闸门槛④）：v5.22.0~v5.23.0 累积的 `static/` 改动需覆盖安装验证；清单见 `docs/agents/ops.md`。**不得把「代码已合并」记成「双端已验证」**。
2. **Tests 徽章数字**：仍是 v5.22.1 的本地全量基线（3006 passed / 3009 collected）。下次本地全量 `pytest tests` + `--collect-only -q` 重跑后，**必须同时更新分子与分母**（README 注释已写明）。
3. **词卡 Step 2/3**（方案稿 `docs/plans/2026-11-09-vocab-card-duplicate-merge.md`）：存量重复 G/S/M 统计与合并、Step 3 建 UNIQUE（届时需同步改写 `tests/test_vocab_identity_upsert.py` 的 PRAGMA 过渡护栏）、三套计数口径统一、`prep_saved` 缺 `refl`、备份还原 / wb 投影写锁统一。
4. **宣传开闸四条门槛**：≥5 份真实三问反馈 / 新手「下载→打开→读到第一篇」无协助成功 / README 首屏 / Android 真机点检。产品演示类内容冻结至门槛全绿。
5. **vault 蒸馏（协议 §6）**：本轮 PITFALL/DECISION 未入 vault，需 `WIKI_PATH` 可用时补（重点：CHANGELOG 顺序根因、UDF 全表扫描的性能结论、`rd-api.js` 导出面守卫）。
6. **待办总入口**：`PROJECT_OVERVIEW.md`「开放待办」与 `docs/reviews/2026-10-16-open-items-backlog.md`。

## 风险与坑

- **发版前置**：tag 必须打在含 bump 的合并提交上；含 `.github/workflows/**` 的 PR **不能**用 `gh pr merge`（token 缺 `workflow` scope），需 SSH 本地 `--no-ff` 合并后 push（`check_master_commit_scope.py` 用 `--first-parent`，PR 分支提交不会误判）。
- **`static/` 改动必须覆盖安装**才在 Android 生效（服务端 `Cache-Control: no-cache` + 安卓 `static.version` 重解包）。
- **文档数字纪律**：写进 README / CHANGELOG 的测试数字必须自己实测；本轮未跑全量，因此沿用旧基线并显式标注，不得凭记忆编数。
- **热层未轮转**：`work.log` 现存 53 条事件，低于轮转阈值 75；下次开工先按 PROTOCOL §3 检查计数。
- **CHANGELOG 插入位置**：新条目插在 FORMAT RULES 注释块之后、当前第一个 `## vX.Y.Z` 之前（降序）；插错会被 `check_release_docs` 判红。
