# 发布链路 runbook：Publish 被跳过 / 孤儿 tag 恢复

> 定位：`docs/README.md` §分层 的 `agents/` 常青运维文档 + 需逐项填写的实证记录模板。
> 证据等级全文统一标注：**[仓内实证]** / **[Vault 复盘实证]**（正式件在 Vault，仓内不可检索）/ **[未实证]**。
> 本 runbook 只描述恢复动作与判据，**不修改 CI 定义**（`.github/workflows/build-release.yml` 保持原样）。

## ⚠️ 未实证声明（MUST）

`gh workflow run build-release.yml --ref <tag>` 补发在本仓 **[未实证]**（`WORKMEMORY/PROJECT_OVERVIEW.md:72`；`docs/reviews/2026-11-13-repo-health-swarm-audit.md:62` P2 #4；`docs/plans/2026-11-13-repo-health-remediation.md:184,362`）。具体未实证三件事：

1. `workflow_dispatch --ref <tag>` 时 `github.ref` 是否变为 `refs/tags/v*`，从而满足 `.github/workflows/build-release.yml:560` 的 `if: startsWith(github.ref, 'refs/tags/v')`；
2. 满足后 `publish-github-release` 是否真的执行并创建/更新 Release；
3. 执行后 release 资产清单是否齐全。

`gh workflow run --help` 显示 `--ref` 接受 branch **or tag**，这只是**[理论可行]**。任何文档、CHANGELOG、work.log、PR 描述 **MUST NOT** 把「理论可行」写成「已验证 / 已实证」。本文 §4 给出实证步骤与状态升级条件；在此之前，路径 2 只能作为「未实证候选」，判据与回落路径见 §3。

## 0. 事实基线

| 事实 | 证据 | 等级 |
|---|---|---|
| `on: push.tags: "v*"` + `workflow_dispatch:`（无 inputs） | `.github/workflows/build-release.yml:3-7` | 仓内定义 |
| `publish-github-release` 有 `needs: [build-windows, build-linux, build-macos, build-android]` 与 `if: startsWith(github.ref, 'refs/tags/v')` | `:555-560` | 仓内定义 |
| Publish 用 `softprops/action-gh-release@v3`，`files: dist/DeLector-*.zip / *.tar.gz / *.apk`，`draft: false`，`name` 取 `github.ref_name` | `:589-620` | 仓内定义 |
| dispatch 到**分支** ⇒ Publish 静默跳过，靠**移 tag** 补跑 | Vault `08-Projects/DeLector/POST-MORTEM-V5.4.0-GITHUB-ACTIONS-TRIPLE-TRAP.md`，转引自 `docs/plans/archive/2026-10-12-release-pipeline-and-docs-consolidation.md:19` 与 `WORKMEMORY/archive/work-2026-10-12.log:27` | [Vault 复盘实证] |
| 某平台 job 红 ⇒ `needs` 不满足 ⇒ Publish `skipped` ⇒ tag 存在但无 Release；已发生三次：`v5.1.1`（2026-09，无人恢复）、`v5.17.0` 首次 tag（2026-10-11，删 tag 重打恢复） | `WORKMEMORY/archive/work-2026-10-12.log:21-27` | [仓内实证] |
| 孤儿 tag `v5.1.1` 已按「删 tag + 记账、不补发」处置（`gh release view v5.1.1` → not found），理由：补发过期版本会让用户看到陈旧产物 | `docs/plans/archive/2026-10-12-release-pipeline-and-docs-consolidation.md:18`、`work-2026-10-12.log:23-24` | [仓内实证] |
| 发布后 MUST 用 `gh release edit <tag> --notes-file <文件>` 覆盖逐版正文 | `build-release.yml:597-599`、`docs/agents/ops.md:233-237` | 仓内纪律 |
| 是否已发布的**唯一判据是 release 清单 / 资产列表，永远不是 run 状态** | `docs/plans/archive/2026-10-12-release-pipeline-and-docs-consolidation.md:19`、`work-2026-10-12.log:27` | 复盘铁律 |

## 1. 触发形态

| # | 形态 | 机理 | 等级 |
|---|---|---|---|
| A | **孤儿 tag**：`v*` tag 已推送，但四个 build job 至少一个红 | `needs` 不满足 → `publish-github-release` `skipped` → tag 存在、Release 不存在 | [仓内实证] `v5.1.1` / `v5.17.0` 首次 tag |
| B | **dispatch 到分支**（含 `gh workflow run build-release.yml` 默认 `--ref master` 或 `--ref <branch>`） | `github.ref = refs/heads/*` → `if` 为假 → 即使四平台全绿也静默跳过 Publish | [Vault 复盘实证] |
| C | **dispatch 到 tag**：`gh workflow run build-release.yml --ref <tag>` | 推测 `github.ref = refs/tags/v*` 可满足 `if` | **[未实证]**，见 §4 |

**识别（只读，先取证再动手）**

