# DeLector 软件著作权申请就绪度补充 Implementation Plan

> **Goal**: 在不推进暂停中的产品线的前提下，以本地安装的 `software-copyright-materials` skill 为材料生成引擎、以仓库文档为可提交真值，补齐软著申报所需的说明书、著作权人声明与口径材料，使仓库达到"可提交"状态。
> **Tech Stack**: Markdown 文档 + 仓库内静态守卫（Python 3.11 / pytest）+ 项目级 skill（`.agents/skills/software-copyright-materials/`，v2.6，本机已优化）；运行时依赖不增，OfficeCLI 1.0.151 / Playwright CLI 0.1.20 为 skill 的外部工具前置。
> **Spec Reference**: 2026-11-21 `dfs-team` 多席位评估报告（本轮对话）；`FEATURES.md`、`CHANGELOG.md`、`docs/adr/INDEX.md`；skill 的 `SKILL.md` 与 `references/*`。
> **Global Constraints**: ① 用户裁决（2026-11-21）：可播放演示素材暂缓、静态图片可用、其余做补充改动；② 2026-11-13 裁决：执行期禁跑全量 pytest，静态闸 / mypy 各档按文件覆盖跑全；③ 一 Task 一分支一 PR；④ commit/push 只走秒级门禁，长验证与提交解耦；⑤ 公开仓不得写入私有库路径（PR #377 / `5102465`）；⑥ skill 产物目录 `软件著作权申请资料/` 已 gitignore，任何 `草稿/` 与 `正式资料/*.docx` 不得进 PR。
> **Branch**: 下列每个 Task 各自从 `master` 切 `<type>/<slug>` 分支、独立 PR 落地（遵循"一 Task 一分支一 PR"）。本轮不声明 `release` / `bookkeeping` 例外——即使多数 Task 是纯文档，本计划含多种类型且需逐项评审，统一走 PR。开工前先建分支，禁止直推 `master`。
> **Repo Invariants Pointer**: `AGENTS.md`（唯一入口）→ `WORKMEMORY/PROJECT_OVERVIEW.md`「红线速查」13 条 → `CONTRIBUTING.md`。所有 Subagent Prompt 引用此指针，不重述规则。

---

## [NOTE] Decisions So Far

- 2026-11-21 用户裁决：**可播放演示视频/GIF 暂缓**；`docs/images/` 下两张静态截图可复用作说明书配图；其余缺口做补充改动。
- 2026-11-13 用户裁决：执行期只对点测试，不跑全量 pytest；README badge（v5.23.4 / 3040-3054）已带时点口径，**不重跑、不改数字**。
- PR #377（`5102465`）：公开仓隐私边界——历史事件正文（`work.log` / `archive/work-*.log`）按协议 §1.3 追加制不改写；本轮不动。
- `FEATURES.md:7` 的"冻结快照"是有意决策（PR #404），保留冻结事实，仅调整会被读成"不代表当前版本"的自损措辞。
- **P2#9 复核不成立**：`README.md` 全文无"14 条"文本，实际列出 12 条限制（`:212-223`）。该条系勘察阶段误数，**不立任务**。
- 当前版本 v5.24.2 的四平台真机/真装路径未验证（活项 9），属产品验证，与软著材料无关，不纳入本轮。
- 2026-11-21 选定并安装 skill 1 `fokkyp/softwarecopyright-skill@software-copyright-materials`（v2.6）到**项目级** `.agents/skills/`，CodeBuddy/Claude Code 为软链；`skills-lock.json` 锁 commit `1159f6d2…`。`.agents/`、`skills-lock.json`、`软件著作权申请资料/` 已入 `.gitignore`。
- 2026-11-21 本地优化该 skill：`SKILL.md` 484→142 行（详细契约推入 `references/`），自带测试 32/32 通过、`quick_validate.py` exit 0。安装时 CLI 报 Gen High Risk（Socket 0 alerts / Snyk Low Risk），脚本未改；`npx skills update` 或重装会覆盖本次优化，`skills-lock.json` 的 hash 仍是原版。
- 2026-11-21 实测：本机 `officecli` 与 `playwright-cli` **均不在 PATH**（Node v24.15.0 在）⇒ skill 工作流的 `environment` 门禁必然触发；未装 OfficeCLI 时按 skill 规则只能生成 Markdown/TXT，不得产出伪成功 DOCX。
- 2026-11-21 用户裁决：**本轮只做四份仓库内 Markdown/声明文档（Task 1~4），Word 提交件与 skill 的 DOCX 生成暂缓**；以后要 Word 时另开一份计划说明（不塞回本计划、不在此扩 Task）。该裁决解除 Fog of War 的"是否需 Word 提交件"未知项。

---

## [NOTE] Skill Contract (material engine vs repository SSOT)

- **引擎 / 产物**：`.agents/skills/software-copyright-materials/SKILL.md`（本地已优化）为申报材料的生成引擎，运行后在**当前工作目录**产出 `软件著作权申请资料/`：`analysis/`、`草稿/`、`截图*/`、`正式资料/`。该目录已 gitignore，skill 自身不执行 git commit / PR。
- **仓库 SSOT**：`docs/USER_GUIDE.md`（Task 1）与 `docs/soft-copyright-source-index.md`（Task 4）是进仓库、可评审、可追溯的产物；与 skill 草稿共用事实源（`FEATURES.md`、`README.md`、`static/views/`、`docs/adr/INDEX.md`），**不复制 skill 的制式草稿**。
- **单一真值**：源码抽取选择以 skill 的 `草稿/代码文件选择.json` 与 `草稿/代码提取清单.json` 为准（经 skill `code-selection` 门禁确认）；仓库清单只做索引与排除理由，不另起一套选择逻辑。
- **门禁映射**：skill 的 `application-fields`（著作权人）与 Task 2 同源、答复一次两处复用；`code-selection` 与 Task 4 同源；`screenshot-method` 按用户裁决走 `user-supplied` 或 `skip`，不走自动截图（本机 CLI 缺失且演示暂缓）；`markdown` 门禁确认的是 skill 草稿，仓库文档另按各 Task 的对点测试核验。
- **不互相驱动**：skill 的产物不自动回写仓库；本计划各 Task 也不要求先跑完整 skill 工作流才能开工——两者并行，交集仅限上述共享事实源与门禁答复。

---

## [NOTE] Active Frontier (Unblocked Tasks)

### Task 1: 交付用户操作说明书 `docs/USER_GUIDE.md` [Tier: 1-Light] [Mode: AFK] [Role: docs-writer]

**Files:**
- Create: `docs/USER_GUIDE.md`
- Modify: `tests/test_writer_mobile.py`（在 `test_readme_first_screen_images_exist` 旁新增 `test_user_guide_images_exist`，约 `:170` 之后）
- Test: `tests/test_writer_mobile.py::test_user_guide_images_exist`（对点，不全量）

**Interfaces:**
- Consumes: `README.md:27-35`（首屏价值主张 + 两张截图路径）、`FEATURES.md:11-26`（能力域清单）、`README.md:210-223`（已知限制 12 条）；可选交叉核对 skill 的 `references/business_understanding_rules.md` / `manual_structure.md` 的"用户视角、按真实页面成章"口径——但**不读取也不依赖** `软件著作权申请资料/` 下的 skill 产物。
- Produces: `docs/USER_GUIDE.md`，固定章节序：`# 用户操作指南` → `## 一分钟认识 DeLector` → `## 安装与启动` → `## 核心功能操作`（精读台 / 五场域句法 / 影子跟读 / FSRS 卡盒 / 备考工坊各一节，每节配图或引用现有截图）→ `## 常见问题与限制`（含 AI 需配置 API Key、无 Key 时返回精简提示的如实披露）。与 skill 的 `草稿/操作手册.md` 保持同一事实口径，但不复制其制式章节骨架。

**SSOT Effect:**
- Reads: `FEATURES.md:42-49`（动词/词条数字）、`FEATURES.md:53-60`（句法数字）、`README.md:14-25`（徽章时点口径）
- Writes: 无机器可读数字产物；`USER_GUIDE.md` 内所有数字**逐字引用** `FEATURES.md` 并标注来源，不新造数字
- Params read: 无
- Hardcoded-literal exemption: `none`

**Injected Instincts:**
- [ ] `[Instinct: Evidence]`: 每个功能小节必须对应一个真实 UI 入口（视图文件在 `static/views/` 存在）或现有截图；不得凭空描述不存在的功能。
- [ ] `[Instinct: Honesty]`: AI 降级行为按 `delector/routes/articles.py:348-359` 的实际返回写，不写成"完全可用"。
- [ ] `[Instinct: No-emoji]`: 遵循 `tools/check_release_docs.py` 的发布面文档无 emoji 规则。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 用户操作说明书。Mode: AFK | Role: docs-writer。先读 `AGENTS.md` → `WORKMEMORY/PROJECT_OVERVIEW.md` 红线速查 → `CONTRIBUTING.md`。TDD 步骤：① 在 `tests/test_writer_mobile.py` 写 `test_user_guide_images_exist`（RED：断言 `docs/USER_GUIDE.md` 存在、其引用的每张图片在 `docs/images/` 真实存在）；② 跑 `python -m pytest tests/test_writer_mobile.py::test_user_guide_images_exist -q` 确认失败；③ 按 Produces 章节序创建 `docs/USER_GUIDE.md`（GREEN），复用 `docs/images/readme-home-hero.jpg` 与 `readme-reader-b2.jpg`，不新增视频/GIF；④ 复跑对点测试确认全绿；⑤ 跑 `python tools/check_release_docs.py` 确认无 emoji；⑥ 返回物理证据（命令 + exit code + 测试数 + git diff --stat）。"

**Step Breakdown:**
- [ ] Step 1: 写失败测试 `test_user_guide_images_exist`（RED）
- [ ] Step 2: 对点跑测试，确认因文件缺失而失败
- [ ] Step 3: 创建 `docs/USER_GUIDE.md`，按 Produces 六节成文（GREEN）
- [ ] Step 4: 复跑对点测试 + `python tools/check_release_docs.py`
- [ ] Step 5: REFACTOR——核对每节功能确有对应视图/截图，删掉无法举证的描述
- [ ] Step 6: Physical Evidence Gate：留存 raw 命令 + exit code 0 + 测试数 + diff stat
- [ ] Step 7: 独立分支原子 commit，走 PR 落地

---

### Task 2: 明确著作权人声明 [Tier: 1-Light] [Mode: HITL] [Role: docs-writer]

**Files:**
- Modify: `README.md:227-229`（`## 许可证` 段）
- Modify: `LICENSE:189`（Apache 附录版权行）
- Test: 无新增测试；物理核验 = `git diff` 显示署名已落地 + `python tools/check_release_docs.py` exit 0

**Interfaces:**
- Consumes: `LICENSE:189`（当前 `Copyright 2026 DeLector Contributors`）、`README.md:227-229`（仅写 Apache 2.0 + 欢迎 PR）
- Produces: README 段落新增 `著作权所有 © 2026 <权利人法定名称>` 一行；LICENSE 附录行同步为同一名称。权利人名称在 HITL 检查点由用户给出（自然人姓名或法人全称），仓库内不预写占位文本。

**SSOT Effect:** `—`（本任务不产生数字）

**Injected Instincts:**
- [ ] `[Instinct: HITL]`: 未在检查点拿到权利人名称前**不许落笔**；不得从 git 配置或 ADR 正文推断后自动填写（署名属法律声明）。
- [ ] `[Instinct: Single-Source]`: README 与 LICENSE 两处名称必须逐字一致，diff 中不得出现两个不同写法。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 著作权人声明。Mode: HITL | Role: docs-writer。**先向用户提问：著作权人登记为自然人还是法人？法定名称是什么？拿到明确答复前停止，不写任何占位符。** 收到答复后：① 修改 `README.md:227-229` 增加 '著作权所有 © 2026 <答复名称>'；② 修改 `LICENSE:189` 为同一名称；③ 跑 `python tools/check_release_docs.py` 确认 exit 0；④ 返回 diff + exit code。"

**Step Breakdown:**
- [ ] Step 1: HITL 检查点——取得权利人法定名称（自然人/法人）
- [ ] Step 2: 修改 README 许可证段（RED 口径：当前无署名）
- [ ] Step 3: 同步 LICENSE 附录行，两处逐字一致（GREEN）
- [ ] Step 4: `python tools/check_release_docs.py` + `git diff` 物理核验
- [ ] Step 5: 独立分支 commit，走 PR

---

### Task 3: 统一对外口径，去除自损表述 [Tier: 1-Light] [Mode: HITL] [Role: docs-writer]

**Files:**
- Modify: `FEATURES.md:7`（冻结快照措辞）
- Modify: `docs/adr/INDEX.md:3`（仓内副本状态说明）
- Test: 无新增测试；物理核验 = `git diff` + `python tools/check_release_docs.py` exit 0

**Interfaces:**
- Consumes: `FEATURES.md:7`（"不代表当前版本的能力边界"）、`docs/adr/INDEX.md:3`（"正式件在私有笔记库，不随仓库分发"）、`README.md:14-25`（徽章时点口径，已正确，**不动**）
- Produces: `FEATURES.md:7` 保留"冻结快照 + 对应 v5.22.1 + 逐版以 CHANGELOG 为准"的事实，去掉"不代表当前版本能力边界"这类会被评审读成功能不全的措辞，改为指向 `CHANGELOG.md` 的中性表述；`docs/adr/INDEX.md:3` 保留"仓内副本"事实，补一句"仓内副本本身即决策记录，可用于说明设计演进"，不删 `authority: synthetic` 等原始标签（逐文件改 19 篇 ADR 反而制造"事后合成"观感）。

**SSOT Effect:** `—`

**Injected Instincts:**
- [ ] `[Instinct: Cross-Doc Pointer]`: 改 `FEATURES.md:7` 时只改措辞，不改其指向 `CHANGELOG.md` 的引用；引用是会漂移的指针，禁止顺手重写 CHANGELOG。
- [ ] `[Instinct: Minimal Edit]`: 只动上述两行；徽章数字、ADR 正文、历史事件正文全部不碰。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 口径统一。Mode: HITL | Role: docs-writer。先读 `AGENTS.md` → `WORKMEMORY/PROJECT_OVERVIEW.md` 红线速查。HITL 检查点：向用户确认是否接受'保留冻结事实、仅改自损措辞'这一保守方案（备选是重写 FEATURES 全文，但会作废冻结决策，不推荐）。确认后：① 改 `FEATURES.md:7`，保留冻结快照事实与 CHANGELOG 指向，去掉'不代表当前版本能力边界'；② 在 `docs/adr/INDEX.md:3` 补一句中性的'仓内副本可作设计演进说明'；③ 跑 `python tools/check_release_docs.py`；④ 返回 diff + exit code。禁止改徽章数字、ADR 正文、work.log。"

**Step Breakdown:**
- [ ] Step 1: HITL 确认保守方案
- [ ] Step 2: 改 `FEATURES.md:7`（RED：现文案含自损措辞）
- [ ] Step 3: 改 `docs/adr/INDEX.md:3`（GREEN）
- [ ] Step 4: `python tools/check_release_docs.py` + diff 核验
- [ ] Step 5: 独立分支 commit，走 PR

---

### Task 4: 编制源代码鉴别材料清单 [Tier: 1-Light] [Mode: HITL] [Role: docs-writer]

**Files:**
- Create: `docs/soft-copyright-source-index.md`
- Test: 无新增测试；物理核验 = 清单内每个路径 `Test-Path`/`ls` 存在 + `git diff --stat`

**Interfaces:**
- Consumes: `delector/nlp_engine/syntax_tree.py`、`delector/nlp_engine/linguistics.py`、`delector/routes/`、`delector/services/writing.py`、`static/js/`（功能实现）；`docs/adr/INDEX.md`（独创性佐证索引）；口径按 skill 的 `references/code_selection_rules.md` 与 `references/copyright_material_rules.md`（前后各 30 页、排除第三方运行时）——不读取 `软件著作权申请资料/` 下产物。
- Produces: 一份清单文档，列明① 建议提交的"前 30 页 / 后 30 页"源文件及顺序（优先自研 NLP/句法、路由、服务，排除 `android/` 内 Chaquopy 运行时与 `.pyc`、`tools/` 内归档脚本）；② 每份文件的功能一句话说明与对应 ADR 编号；③ 说明书指向 `docs/USER_GUIDE.md`。此清单是**仓库内可评审索引**；skill 跑起来后的 `草稿/代码文件选择.json` / `代码提取清单.json` 是执行态单一真值，二者选择口径应一致但不互相读写。

**SSOT Effect:** `—`

**Injected Instincts:**
- [ ] `[Instinct: Exclude-Vendored]`: 明确排除 `android/` 下 7797 个 `.py` / 6996 个 `.pyc` 依赖与生成物、`*.pyc`、锁文件——它们是第三方运行时，不是本作品源代码。
- [ ] `[Instinct: HITL]`: 申报机构对源文件页数/格式的具体要求由用户确认；清单按通用"前后各 30 页"编制，不假定地方规则。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: 源代码鉴别材料清单。Mode: HITL | Role: docs-writer。HITL 检查点：确认用户是否有申报机构的页数/格式特别要求；无则按前后各 30 页通用口径。创建 `docs/soft-copyright-source-index.md`：① 列自研源文件顺序（nlp_engine → routes → services → static/js），排除 android 依赖与 pyc；② 每个文件一句话功能 + 对应 ADR 编号（从 `docs/adr/INDEX.md` 取）；③ 说明书指向 Task 1 的 `docs/USER_GUIDE.md`。对每个列出的路径做存在性核验。返回核验命令 + exit code 0 + diff stat。"

**Step Breakdown:**
- [ ] Step 1: HITL 确认页数口径
- [ ] Step 2: 列出候选源文件并逐个核验存在
- [ ] Step 3: 创建清单文档（GREEN）
- [ ] Step 4: 路径存在性物理核验 + diff
- [ ] Step 5: 独立分支 commit，走 PR

---

## [NOTE] Fog of War (Not Yet Specified)

- **[权利人主体]**: 自然人 / 法人未定 → blocks Task 2 的 HITL 检查点；由用户答复后解除。
- **[申报机构格式要求]**: 说明书章节、源代码页数、是否需运行截图的细则未确认 → 影响 Task 1 / Task 4 的产出格式；本计划采用通用默认，收到细则后以 Deviation Table 记录偏差。
- **[当前版本全量测试报告]**: 执行期禁跑全量的裁决下不产出；若申报机构硬性要求，走一次性核验并与 commit/push 解耦（见 Deferred Gap Register）。
- **[OfficeCLI 1.0.151 全局安装]**: skill 生成 Word/TXT 的必需外部工具，本机不在 PATH（2026-11-21 实测）；`environment` 门禁要求用户确认安装并重启 Codex。已由 2026-11-21 裁决移出本轮范围，仅在新开的 Word 计划里处理，不阻塞四 Task。

---

## [NOTE] Deferred Gap Register

| gap | why deferred | trigger that forces revisiting | owner |
|---|---|---|---|
| 可播放功能演示视频 / GIF | 用户 2026-11-21 明确暂缓；两张静态截图已满足界面呈现 | 申报机构要求演示视频，或用户恢复宣传线（活项 1 四门槛全绿） | 用户 |
| 当前版本（v5.24.x）全量 pytest 证据 | 2026-11-13 裁决执行期禁跑全量；README badge 已带时点口径，非申报阻断 | 申报机构要求当前版本测试报告（一次性、与 commit 解耦执行） | 用户 |
| Dockerfile 改 `requirements.lock.txt`（现用 `requirements.txt`） | 软著不要求 Docker 复现；改动需 `docker build` 物理证据，本环境未验 | 申报材料需 Docker 复现证明，或 CI 新增 docker build 门 | 维护者 |
| `server.py:408` 模块级 `create_app()` 建库副作用 | 非软著要求；模块级 `app` 是 `start.py` 与全部 TestClient 夹具的共同入口，改动回归风险高 | 出现真实 import 期崩溃或数据目录只读故障 | 代码负责人 |
| `tools/gen_rich.py` / `tests/test_german_workbench.py` 的 `D:/Ran` 路径、`tts.py:33` 公开令牌 | 前者是归档生成链的外部路径快照（脚本已注明仓库内不可运行），后者是 Edge TTS 公开协议常量且已有注释；gitleaks 不报，非申报阻断 | 提交前隐私扫描命中，或申报机构要求源码无个人路径 | 维护者 |
| ADR 正文的 `authority: synthetic` / `unreviewed` 标签逐篇清理 | 逐文件改 19 篇反而制造"事后合成"观感；Task 3 的索引层说明已足够 | 申报机构要求把 ADR 作为独创性证明单独提交 | 用户 |
| 运行 skill 生成 `软件著作权申请资料/` 下的 Word/TXT 草稿与正式件 | 2026-11-21 用户裁决本轮只做四份仓库内 Markdown/声明文档；Word 提交件暂缓、以后另开计划说明。OfficeCLI 1.0.151 与 Playwright CLI 0.1.20 本机均不在 PATH，仓库四 Task 不依赖这些产物 | 用户决定启用 Word 提交件并**另开一份计划**（届时先解决 OfficeCLI 全局安装 + 重启 Codex；截图再决策 `user-supplied` / `skip`，自动截图需装 Playwright CLI） | 用户 |
| skill 本地优化（SKILL.md 484→142 行）的持久化 | 改动落在 gitignored 的 `.agents/skills/`，不入仓；`npx skills update` / 重装会用上游 484 行版覆盖，`skills-lock.json` 的 hash 仍对应原版 | 用户要求随上游升级 skill，或换机器重建环境时需要重做精简 | 用户 |
| skill 安装时报的 Gen High Risk 评级 | 仅 Gen Agent 报高风险（Socket 0 alerts / Snyk Low Risk）；本轮只改文档层、未审脚本，作为本地工具不阻断仓库任务 | 在生成正式申报材料前要求对该 skill 脚本做安全审计 | 用户 |

---

## [NOTE] Out of Scope

- 可播放演示素材（视频 / GIF / 动图）——用户裁决暂缓，静态图片可用；skill 的 Playwright CLI 自动截图路径同样不启用。
- **Word 提交件与 skill 的 DOCX/TXT 生成**——2026-11-21 裁决本轮不做，以后另开计划说明；本计划只有四份仓库内 Markdown/声明文档。
- skill 自身产物入库（`软件著作权申请资料/`，含 `草稿/` 与 `正式资料/*.docx`）——已 gitignore，只在本机留存，不进任何 PR。
- 生产代码重构、发版、tag ——项目自 2026-11-10 阶段性暂停；本轮仅补文档与声明。
- 真机验证（Android / Windows / Linux 应用内更新，活项 9）——与软著材料无关。
- 历史事件正文改写（`work.log` / `archive/work-*.log`）——协议 §1.3 追加制。

---

## [NOTE] Deviation Table

*(post-execution, filled before merge；三列不得增减)*

| plan text | what was actually built | why |
|---|---|---|
| — | — | —（执行后填写；无偏差则写"无偏差"） |
