# commit 节奏与 git 管理评估（DeLector，master @ `d93089b`）

**Date**: 2026-10-16 · 分支 `chore/swarm-audit-master`（评估专用）
**席位**：`code-reviewer` ×2（**commit 节奏与历史纪律** / **git 管理与仓库卫生**），均只读、只跑只读 git 命令
**Findings**：**10** 条（合并后）← 原始 **14** 条。**无 P0**（密钥与历史卫生干净）。2 P1 + 8 P2。

---

## 一、commit 节奏：**健康，不是噪声**

**一句话结论**：447 提交/30 天 ≈ 15/天，是「**PR 内任务级原子提交**」与「**协议驱动的簿记事件**」两股叠加，不是过碎。

| 证据 | 数据 |
|---|---|
| PR 合并节奏 | 90 个 merge / 30 天 ≈ **3 PR/天** |
| PR 内提交数 | 4~14 个、平均约 2.3（`ae8c3fd`=14、`d919d42`=13、`a4984c2`=10、`6024fb0`=4） |
| 空泛消息 | `wip`/`fix`/`update` 命中数 = **0** |
| 合并形态 | 90 个 merge 全为 `Merge pull request #N from …`（`--no-ff`），合并信息带 PR 号 + 分支名 + 合并不变量 |
| 分支拓扑 | 仅 4 个分支；唯一未合分支是活跃在途的 `feat/judge-gaming-experiment`（12 提交，最后活动 = 今天） |
| 簿记节律 | `work.log` 被改 83 次 = NOTE/WORK_END/DECISION 事件协议（一个事件一提交）——**不应为压低提交数而合并** |
| 版本面纪律 | 发版稳定六件套（CHANGELOG/README/PROJECT_OVERVIEW/gradle/index.html/sw.js，v5.17.0 起加 `core/version.py` + `test_app_version_source.py`）；`40a9f88` 四处版本串一致 + `assert_tag_matches_app_version` 构建期硬闸 |

**规则生效后 100% 合规**：`--since=2026-10-14 --first-parent --no-merges master` 的 20 条直推**只碰 `WORKMEMORY/` + `docs/`**（代码/CI/打包命中数 = 0）。

---

## 二、P1（2 条）

### P1-1 · 分支纪律**没有机械闸**；规则落地前 25 个实现类提交直推 master
**[code-reviewer]** 证据：`docs/agents/ops.md:202-216` 自述「2026-10-13『去控制台 + 桌面化观感』那批…全程直推 `master`、零 PR」，并承认「分支纪律没有机械闸」。实测复核：`--since=2026-10-09 --until=2026-10-14 --first-parent --no-merges master` 中 `feat/fix/ci/test/perf` 前缀共 **25 条**，含生产代码与 CI 定义（例：`a2c4621` 改 `desktop.py`+55 与 `tests/test_desktop_shell.py`+132；`41cb430` 改 CI；`f66d203` 改发布链路）。
**失败场景**：直推不经 PR ⇒ 无 review、无 PR 级 CI 门禁；**已有实发事故** —— `f49d359 fix(ci): 修 master push 上 CI 变红（打包面检测 job 缺 checkout）`，即一次直推把 master 推红后才回头补。规则 2026-10-14 才写进可见文档（`fbeca12`/`4897a6f`/`46487ac`），此前 agent 按 `AGENTS.md` bootstrap **根本读不到这条规矩**（ops.md:212-214 自述根因）。
**修法**：加一条廉价机械闸 —— pre-push hook 或 CI job 断言「`master` 上非 merge 提交的改动面 ⊆ {WORKMEMORY/, docs/, README.md, CHANGELOG.md, static/index.html, static/sw.js, android/app/build.gradle, delector/core/version.py}，否则 fail」（与已有 tag 闸同族，`ops.md:215` 自己指出了这个对照）。

### P1-2 · `.gitignore` 覆盖缺口：`launch.log` / `launch.log.1` / `lan-address.txt` 未忽略，且默认可落仓库根
**[code-reviewer]**（**编排者已独立复核**：`git check-ignore` 三者均 **NOT-IGNORED**；产物确由 `desktop.py:46/51/58` 产生；**历史从未进过这三个文件**）
证据链：`desktop.py:126` `resolve_log_path() = resolve_data_dir(env) + LOG_FILE_NAME`；`core/data_dir_bootstrap.py:118-129` `resolve_data_dir`：**便携开关命中时 `return program_dir()`（= 仓库根）**；`.env.example:5` 附近注释还背书「留空（不设）= 仓库根，即桌面端默认」。
**失败场景**：开发者从源码跑桌面壳（`DELECTOR_PORTABLE=1 python desktop.py` 或 `DELECTOR_DATA_DIR=.`）⇒ 三个文件生成在仓库根，`git status` 不标 `!!` ⇒ 一次 `git add -A` 把**运行态日志（启动堆栈 / 端口冲突详情）与内网 IP 地址**提交进历史 —— 与 `.gitignore:21-24` 自己写下的理由完全同类（「一次 `git add -A` 就会把用户数据提交进历史」）；`.githooks/pre-commit:55-68` 的文件名黑名单也不含 `.log`/`.txt`，钩子拦不住。
**修法**（3 行）：
```gitignore
/launch.log
/launch.log.*
/lan-address.txt
```

---

## 三、P2（8 条）

| # | 发现 | 证据 | 修法 |
|---|---|---|---|
| P2-1 | **实现与簿记混装**（7 个提交） | `8f07820`/`6a3aca4`/`24b7c2e`/`ad556a1`/`949061a`/`7ce6191`/`fbeca12` 同时改 `WORKMEMORY/*` 与实现/测试 ⇒ `git log -- WORKMEMORY` 与 `git log -- src` 边界糊掉，无法单独回滚一段记忆或单独 cherry-pick 一个修复 | PR 内拆出 `docs(workmemory):` 提交（**PR #137 的 `55e0f0d`/`555cd4a` 已是范式**，照抄即可） |
| P2-2 | **批量子提交把多件事揉进一个 commit** | `59ac353 perf(data): 数据面成本账 P1-5~8`（11 文件 / +1448，含 4 项互不相关的优化）⇒ bisect 命中后仍需在 1448 行里人工二分；单项回归无法单独 revert | 一个 PR 可以，提交按「一项一提交」拆（`eae739f→76fdccf→0cba260→c108124→e42f3cd` 的 T1~T5 是范式） |
| P2-3 | **行号锚点基本缺席**（符号级锚点 ~98 处） | 符号锚在重命名/搬移后静默失效；行号至少能暴露「代码已不在原处」。附带：`dbe0e70` 消息里混入一个俄语词「почему」 | 保持符号锚（对重构更稳），**接受现状**；仅记录「声称的行号锚点未全面落实」 |
| P2-4 | `.superpowers/` **缺根级兜底** | `.gitignore:30-33` 为 `.mypy_cache/`/`.ruff_cache/` 加了根级兜底并写明理由；而 `.superpowers/` 靠嵌套 `.superpowers/sdd/.gitignore`（内容 `*`）自忽略 ⇒ 工具升级/重建时 `git status` 干净、`git add -A` 把整棵工具缓存提交 | 补一行 `.superpowers/`，与 `.mypy_cache/` 同级 |
| P2-5 | **松散对象堆积** | `git count-objects -vH`：count 7181 / size 49.10 MiB；`gc.auto` 疑似未生效（未查证） | `git gc` 一次；查 `gc.auto`/`gc.autoPackLimit` 配置 |
| P2-6 | **9 个跟踪文件工作区行尾 `w/mixed`** | `git ls-files --eol` 中 9 个（`.agent-rules.md`、`.cursorrules`、3 份 work-2026-09-1x.log、`linguistics.py`、`syntax_score.py`、`hard-sentences.js`、`test_desktop_data_dir_bootstrap.py`），blob 均 `i/lf`（**历史干净，问题只在工作区**） | 潜伏的口径不一致（非正在发生的错误）；`git add --renormalize` 一次性收口 |
| P2-7 | **CRLF 纪律实质依赖个人配置而非仓库契约** | `.gitattributes` 有 4 组规则且**实测生效**（`agent/**/*.go` 全 `attr/text eol=lf` + `w/lf`，与 gofmt 假阳性事故闭环）；但 `.py/.md/.js` 无 attr，实测 `attr/` 空 + `w/crlf` —— 只因为本机 `core.autocrlf=true`（**系统级** Git 配置）。Linux/macOS clone 拿到 LF ⇒ 同一文件在不同机器上格式不同 | `.gitattributes` 增加 `* text=auto eol=crlf`（置于 `*.go text eol=lf` **之前**，让具体规则覆盖通用规则），把 CRLF 从「本机副作用」升级为「仓库契约」 |
| P2-8 | `.env.example` 注释与代码矛盾（**与结构评估 P1-2 同源**） | `.env.example:5` 说「留空 = 仓库根，即桌面端默认」；实际 `data_dir_bootstrap.py:125-129` Windows 默认 `%LOCALAPPDATA%\DeLector`，只有 `DELECTOR_PORTABLE` 才落程序目录。它正是 P1-2 的**认知放大器** | 改为「Windows 默认 `%LOCALAPPDATA%\DeLector`；设 `DELECTOR_PORTABLE=1` 才落到程序所在目录」 |

**另附（P2，待确认）**：`android/gradle/wrapper/gradle-wrapper.jar` 未入库（`gradle-wrapper.properties` 在）⇒ 干净 checkout 上 `./gradlew` 缺 jar；若 CI 有缓存则不暴露。修法：确认 CI 是否依赖；若故意排除请在 `android/build_apk_guide.md` 写明理由。

---

## 四、合理、保持的部分

1. **PR 内任务级原子提交 + 每条提交自带回归锁与变异自证**：`598983d`（P0 死锁）、`dbe0e70`（发版门守卫）、`80c3aa0`（超时护栏反转）三条消息都写「症状/根因/修复/回归锁/门禁实测」，是「为什么」而非「做了什么」的范本；这类密度在非合并提交里是主流。
2. **`--no-ff` + 可读合并信息**：90 个 merge 均带 PR 号、分支名、合并方式变更原因与验收数据（如 `ae8c3fd` 记「服务端合并被 OAuth scope 拒绝 ⇒ 本地 `--no-ff`」）。
3. **簿记节律与协议对齐**：一个事件一个提交，不应合并；`be40ffd`/`58985af` 还有事件头自查纠错。
4. **密钥与历史卫生干净**：HEAD 树高熵正则扫描 0 命中（`sk-`/`Bearer `）；历史上从未新增 env/keystore/credential 文件；被删文件里无敏感文件；`.githooks/pre-commit` 有自述的全量扫描记录（2026-08-19）。
5. **`.gitignore` 按「类别 + 理由」分层**（85 行），注释解释*为什么*；`.gitattributes` 对 go/bat/二进制生效（go 那组有事故闭环）；`DeLector.spec` 本地产物边界由 `test_server.py:4562` 的**显式 skip** 钉住（不是静默 `if`，不会成为死绿测试）。

---

## 五、建议顺序

1. **P1-2 先修**（3 行 `.gitignore`，消掉「运行态日志 + 内网 IP 进历史」的真实风险，且成本为零）。
2. **P1-1 加机械闸**（pre-push hook 或 CI job；这是本仓已实发过事故的纪律缺口，规则本身 2026-10-14 才落地）。
3. P2 里 **P2-1/P2-7/P2-8** 同批（提交拆分习惯 + `.gitattributes` 收口 CRLF 契约 + 注释与代码对齐）；**P2-5**（`git gc`）随手；**P2-4/P2-6/P2-3** 登记待办。

## ⚠️ UNVERIFIED（按纪律未跑，需更重遍历）

1. **全历史逐 blob 密钥扫描未做** —— 「历史无密钥」建立在 HEAD 树扫描 0 命中 + `.githooks/pre-commit:5-7` 的**自述**（2026-08-19 全量扫过可达提交与 fsck 悬空对象）之上，该声明**未能独立验证**。本应跑：`git rev-list --all | xargs -n 50 git grep -I -E 'sk-…|AKIA…|ghp_…|-----BEGIN …PRIVATE KEY-----'` + `git fsck --lost-found --unreachable` 后对悬空 blob 同样扫描。
2. **squash/rebase 是否混用** —— 只抽样 5/90 个 merge 做 `^1..^2` 差集，其余 85 个未验。
3. **每个提交自身是否绿灯落地** —— 只读了消息自报的门禁数字（如 1984 passed），未在对应 sha 上复跑。
4. **`gc.auto` 配置未查证**（`git config --get gc.auto` 即可，属轻量但本轮未跑）。
5. **`static/index.html` 23 次改动是否每次都有对应版本面动作** —— 只抽查 4 对（均同日闭环）。
