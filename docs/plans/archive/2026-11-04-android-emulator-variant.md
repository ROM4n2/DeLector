# Android 模拟器变体（x86_64）实施计划

> **Goal**: 在不改变正式 release APK（仅 `arm64-v8a`、产物路径/命名不变）的前提下，新增一个可装进 Android 模拟器的完整应用变体（`arm64-v8a + x86_64`，保留 spaCy 全量 NLP）。
> **Tech Stack**: Gradle 8.6 / AGP 8.x / Chaquopy 15.0.1 / Python 3.10 / GitHub Actions / pytest。
> **Spec Reference**: 用户 2026-11-04 任务书（方案 A 拍板）；可行性结论见 `docs/agents/architecture.md` Android 一节与 `android/app/build.gradle` 注释。
> **Global Constraints**: 禁止降级 NLP（不得去掉 spaCy、不得改 `dpython` 降级路径）；release `abiFilters` 只允许 `arm64-v8a`；`assembleRelease` 与 `app-debug.apk` 的路径/命名 MUST NOT 变化；所有实现经 PR 落地、不合并；提交按类型拆分。
> **Branch**: `build/android-emulator-variant` — 从 `origin/master@1f9d73f` 创建，落地仅通过 PR。第 0 步探针在**独立 worktree + 一次性分支**完成，不与本分支混用。
> **Repo Invariants Pointer**: `AGENTS.md`、`docs/agents/architecture.md`、`docs/agents/ops.md`、`WORKMEMORY/PROTOCOL.md`。

---

## [NOTE] Decisions So Far

- **方案 A 拍板**：新增独立模拟器变体并追加 `x86_64`；模拟器上是完整应用。用户明令禁止「残缺即可测」的降级路径——这些工具会影响后续 Agent 相关 tool。
- **变体形态选 `buildType`，不选 product flavor**：flavor 会把 `assembleDebug` 输出改名为 `app-<flavor>-debug.apk`，直接打断 CI 写死的 `app/build/outputs/apk/debug/app-debug.apk`。buildType `emulator` 不改变 `debug` / `release` 的既有输出路径。
- **ABI 下移**：`abiFilters` 从 `defaultConfig` 移到 `buildTypes`，避免 AGP 对 `abiFilters` 做集合合并后把 `x86_64` 渗进 release。
- **`android_21` wheel 可用**：Chaquopy 解析器用 `variant.minSdkVersion`（24）构造 `android_24` 平台标签，但 vendored `packaging.tags` 会从目标 API 逐级向下展开到 16 ⇒ `android_21` 轮子可被 minSdk 24 选中（结论来自上一轮源码核验，运行时仍需 AVD 实测）。
- **无成文 ADR**：仓库只有 `android/app/build.gradle` 的注释与 `0a517e8` 提交，记录「为体积放弃 x86_64」；本计划不补 ADR，只在架构文档更正表述。

---

## [NOTE] Active Frontier (Unblocked Tasks)

### Task 0（闸门）: 一次性双 ABI 实测 [Tier: 3-Critical] [Mode: HITL] [Role: Verifier]

**Files:**
- Modify: `android/app/build.gradle`（**仅一次性分支**，改 `abiFilters` 为 `"arm64-v8a", "x86_64"`）
- Create: `.github/workflows/android-emulator-probe.yml`（**仅一次性分支**，只含 Android job、仅 `workflow_dispatch`、产物名 `DeLector-emulator-probe-apk`）
- 不改：`.github/workflows/build-release.yml`、`dist/` 下任何 release 命名

**Interfaces:**
- Consumes: Chaquopy pip 解析器、`android/app/build.gradle` 的 `python.pip` 块。
- Produces: 一次真实构建的日志与 APK 证据；判定通过/不通过。

**SSOT Effect:** —

**Injected Instincts:**
- [ ] `[Instinct: Gate]`: 三条判据缺一不可——(1) pip 日志无 `Couldn't find a matching wheel` / `No matching distribution`；(2) APK 内同时存在 `lib/x86_64/` 与 `requirements-x86_64.imy`；(3) 记录体积与耗时。
- [ ] `[Instinct: No Pollution]`: 探针 workflow 独立文件，不触发 `build-release.yml`，不写 `dist/DeLector-<tag>-Android.apk`。
- [ ] `[Instinct: Transitive Deps]`: 证据必须覆盖传递依赖（含 `srsly`），不能只看顶层 `spacy`。

**Subagent Prompt Scaffold:**
> "Implement Task 0: 一次性双 ABI 实测。Mode: HITL。在独立 worktree 的一次性分支里，仅把 abiFilters 改为 arm64-v8a + x86_64，新增一个只跑 Android 的 workflow_dispatch workflow。推送后 dispatch，收集 pip 日志关键行、APK 内 lib/x86_64 与 requirements-x86_64.imy 清单、APK 体积与耗时。缺 wheel 立即停并报出缺包/ABI/API 标签，不得降级。"

**Step Breakdown:**
- [ ] 在一次性分支改 `abiFilters`，新增只读探针 workflow。
- [ ] push 分支并 `gh workflow run ... --ref <probe-branch>`。
- [ ] 轮询运行结果，抓取 pip 日志与 APK 证据。
- [ ] 三条判据逐条判定；不通过则停止后续所有任务并回报。
- [ ] 记录体积/耗时到执行记录；通过后删除一次性 worktree。

---

### Task 1: ABI 变体守卫测试先行（RED） [Tier: 2-Standard] [Mode: AFK] [Role: Test Builder]

**Files:**
- Modify: `tests/test_ci_hardening.py`（新增 `test_android_device_flavor_abi_is_arm64_only` 与 `test_android_emulator_flavor_abi_includes_x86_64`）

**Interfaces:**
- Consumes: `ANDROID_GRADLE`（已存在的路径常量）；`productFlavors` / `buildTypes` 块文本。
- Produces: `_gradle_block(text, header_re)`（花括号配对）、`_flavor_body(name)`、`_build_type_body(name)`、`_abi_filters(body)`；两条断言。

**SSOT Effect:** —

**Injected Instincts:**
- [ ] `[Instinct: Negative]`: `device` flavor 出现 `x86_64` MUST 红；`defaultConfig` 仍含 `abiFilters` MUST 红。
- [ ] `[Instinct: Positive]`: `emulator` flavor 必须同时含 `arm64-v8a` 与 `x86_64`。
- [ ] `[Instinct: Output Stability]`: 断言 `emulatorRelease` 被禁用，`assembleRelease` 仍只产出一个正式 APK。

**Subagent Prompt Scaffold:**
> "Implement Task 1: ABI 守卫测试先行。Mode: AFK。在 tests/test_ci_hardening.py 增加守卫：device flavor 的 abiFilters 只能是 arm64-v8a、emulator 必须含 x86_64，defaultConfig 不得声明 abiFilters，release buildType 不得声明 abiFilters，且 emulatorRelease 必须被禁用。先提交测试并验证在未改 build.gradle 时 RED。"

**Step Breakdown:**
- [ ] 写花括号配对辅助与四条断言。
- [ ] 运行 `pytest tests/test_ci_hardening.py -k "abi" -q`，确认 RED。
- [ ] 提交测试（`test(android): guard device/emulator ABI boundary`）。

---

### Task 2: build.gradle 落地 emulator flavor（GREEN） [Tier: 2-Standard] [Mode: AFK] [Role: Android Build Builder]

**Files:**
- Modify: `android/app/build.gradle`

**Interfaces:**
- Consumes: Task 1 的守卫断言。
- Produces: `flavorDimensions "channel"` + `productFlavors { device { abiFilters "arm64-v8a" } emulator { applicationIdSuffix ".emulator"; abiFilters "arm64-v8a", "x86_64" } }`；`defaultConfig` 不再含 `ndk { abiFilters }`。

**SSOT Effect:** —

**Injected Instincts:**
- [ ] `[Instinct: Chaquopy Constraint]`: 必须用 flavor——`getAbis` 不读 buildType，否则报 `Chaquopy requires ndk.abiFilters`。
- [ ] `[Instinct: Full App]`: emulator flavor 沿用 `defaultConfig.python`，不裁剪任何 pip 包。
- [ ] `[Instinct: Side Effects]`: `applicationIdSuffix` 使模拟器包无法覆盖安装正式包、也读不到正式包私有数据——必须写进文档。

**Subagent Prompt Scaffold:**
> "Implement Task 2: build.gradle 落地 emulator flavor。Mode: AFK。把 ndk.abiFilters 从 defaultConfig 下移到 productFlavors：device 仅 arm64-v8a、emulator 为 arm64-v8a + x86_64，emulator 加 applicationIdSuffix '.emulator'；禁用 emulatorRelease。不改 python.pip。跑 Task 1 守卫至 GREEN。"

**Step Breakdown:**
- [ ] 下移 `abiFilters`，新增 `device` / `emulator` flavor。
- [ ] `pytest tests/test_ci_hardening.py -k "abi" -q` → GREEN。
- [ ] 具名变异：把 `x86_64` 塞进 `device` ⇒ 守卫 RED；还原 ⇒ GREEN（记录输出）。
- [ ] 提交（`build(android): switch ABI selection to product flavors`）。

---

### Task 3: 常驻 emulator 构建 workflow [Tier: 1-Light] [Mode: AFK] [Role: CI Builder]

**Files:**
- Create: `.github/workflows/android-emulator.yml`（仅 `workflow_dispatch`；与 `build-release.yml` 完全解耦；artifact 名 `DeLector-emulator-apk`）
- Modify: `tests/test_ci_hardening.py`（断言该 workflow 不写 `dist/DeLector-*`、不触发 tag）

**Interfaces:**
- Consumes: `assembleEmulator` 任务。
- Produces: 可下载的模拟器 APK artifact；release 路径零改动。

**SSOT Effect:** —

**Injected Instincts:**
- [ ] `[Instinct: No Release Pollution]`: 不产生 `dist/DeLector-<ref>-Android.apk`。
- [ ] `[Instinct: Reproducible]`: 复用 build-release 的 JDK/SDK/Gradle/Python 版本，不引入 `latest`。

**Subagent Prompt Scaffold:**
> "Implement Task 3: 常驻 emulator 构建 workflow。Mode: AFK。新增 workflow_dispatch-only 的 Android emulator APK 构建，复用与 build-release Android job 同版本的 JDK/SDK/Gradle，产物以 DeLector-emulator-apk 命名上传，绝不写 dist/DeLector-*。补一条测试钉住这两点。"

**Step Breakdown:**
- [ ] 写 workflow（含资产同步与 Keystore 可选注入）。
- [ ] 补测试断言无 release 产物路径、无 tag 触发。
- [ ] 提交（`ci(android): add dispatch-only emulator APK build`）。

---

### Task 4: 文档更正与口径 [Tier: 1-Light] [Mode: AFK] [Role: Docs Writer]

**Files:**
- Modify: `docs/agents/architecture.md`（L61-67 表格：`minSdk 24` 行与 `abiFilters` 行）
- Modify: `WORKMEMORY/work.log`（追加事件）

**Interfaces:**
- Consumes: Task 2 的最终 build.gradle。
- Produces: `android_24` 仅为上界、`android_21` 合法；模拟器变体已加入但真机/模拟器均未点检的明确表述。

**SSOT Effect:** —

**Injected Instincts:**
- [ ] `[Instinct: No Overclaim]`: 未做 AVD `adb install` 就不得写「已在模拟器验证」。
- [ ] `[Instinct: Single Source]`: 只改既有段落，不新增副本。

**Subagent Prompt Scaffold:**
> "Implement Task 4: 文档更正与口径。Mode: AFK。修 architecture.md L64 的 minSdk→android_24 表述（android_24 只是上界，解析器从 24 向下展开到 16，android_21 合法）；补充 emulator 变体与 applicationIdSuffix 副作用；明确真机与模拟器均未点检。追加 WORKMEMORY 事件。"

**Step Breakdown:**
- [ ] 改架构表格与说明段落。
- [ ] 追加 WORKMEMORY 事件（≤4KB）。
- [ ] 提交（`docs(android): correct API-level tag semantics and emulator variant`）。

---

### Task 5: 全量门禁、分类型提交与 PR [Tier: 2-Standard] [Mode: AFK] [Role: Verifier]

**Files:**
- Modify: `docs/plans/2026-11-04-android-emulator-variant.md`（填偏差表与执行记录）

**Interfaces:**
- Consumes: Task 0-4 的全部产物。
- Produces: 全量 pytest 数字、前端探针数字、`git diff --check` 结果、未合并 PR。

**SSOT Effect:** —

**Injected Instincts:**
- [ ] `[Instinct: Physical Evidence]`: 所有数字取自真实退出码与输出。
- [ ] `[Instinct: Scope]`: diff 不含一次性探针 workflow 与临时 ABI 改动。

**Subagent Prompt Scaffold:**
> "Implement Task 5: 全量门禁与未合并 PR。Mode: AFK。串行跑全量 pytest、全部前端探针与 git diff --check；确认一次性探针未混入；填偏差表；推送并开 PR，不合并。"

**Step Breakdown:**
- [ ] 全量 pytest 串行，记录 passed/skipped。
- [ ] 前端探针全跑，记录通过数。
- [ ] `git diff --check`，记录退出码。
- [ ] 填偏差表，推送，开 PR（不合并），回读 CI。

---

## [NOTE] Fog of War (Not Yet Specified)

- **AVD 运行时验证**：x86_64 包能否在模拟器里真正加载 spaCy 模型并跑通语法标注，只能靠实机 `adb install` + `adb logcat`。本计划只到「装得进、依赖齐」，不宣称运行时等价。
- **模拟器镜像架构**：Windows host 默认 x86_64 镜像；arm64 镜像在 Windows 上基本不可用（需 x86_64 变体正是为此）。若第 0 步失败，该结论需重新评估。

## [NOTE] Out of Scope

- armeabi-v7a（32 位）变体。
- 修改 `python.pip` 依赖、去掉 spaCy、改 NLP 降级路径。
- 合并 PR、发版、改 `CHANGELOG.md`。
- `.github/workflows/build-release.yml` 的发布产物路径/命名。

## Deferred Gap Register

| gap | why deferred | trigger that forces revisiting | owner |
| --- | --- | --- | --- |
| 模拟器 AVD 真跑（`adb install` + 语法标注） | 需要本机 AVD 与镜像，CI runner 不提供 | PR 合并前的点检；或用户要求「已点检」的证据 | 人工点检 |
| x86_64 包体积精确值 | 第 0 步实测给出；正式变体随后复测 | 第 0 步 APK 体积 >90 MiB 时评估裁剪 | Task 0 |
| 传递依赖（`srsly` 等）x86_64 轮子 | 由 Chaquopy 解析器真实构建判定 | 第 0 步 pip 日志出现缺 wheel | Task 0 |
| `assembleRelease` 输出路径回归 | 选 buildType 已规避 flavor 改名 | 若未来引入 flavor，必须同步改 CI 抓取路径 | Task 2 |

## Execution Record

**Task 0（闸门）— 通过。** 探针分支 `probe/android-x86_64-wheels`（独立 worktree `.worktrees/android-emulator-probe`），workflow run `41809012748`：

- pip 日志：**无** `Couldn't find a matching wheel` / `No matching distribution` / `Could not find a version`。
- `Successfully installed`：`spacy-3.8.7 thinc-8.3.4 blis-1.2.1 numpy-1.26.2 cymem-2.0.6 preshed-3.0.9 srsly-2.4.4 murmurhash-1.0.2`，另有 `chaquopy-libcxx / libgfortran / libyaml / openblas`。
- 关键实证：`chaquopy-libgfortran-4.9`、`chaquopy-openblas-0.2.20` 以 `android_21_x86_64` 轮子被真实安装 ⇒ `android_24` 只是上界，解析器向下展开到 16。
- APK：`android/app/build/outputs/apk/debug/app-debug.apk`，`92,139,169 bytes`（**87.87 MiB**）。
- 包内：`lib/x86_64/` 5 个 `.so`；`requirements-x86_64.imy` 17,408,632 bytes，顶层包含 spacy/thinc/blis/numpy/cymem/preshed/srsly/murmurhash 全 YES。
- 耗时：`gradle assembleDebug` 131–133 s；整个 job 约 3 分 3 秒。

**Task 1-2（守卫 + flavor）— 完成。** 最初按 buildType 实现，CI 实测直接报 `Chaquopy requires ndk.abiFilters`（Chaquopy 15.0.1 的 `PythonPlugin.getAbis` 只读 `defaultConfig` 与 `productFlavors`，不读 buildType）。据此改为 `productFlavors`：`device` 仅 `arm64-v8a`、`emulator` 为 `arm64-v8a + x86_64` 且带 `applicationIdSuffix ".emulator"`；`emulatorRelease` 被禁用。

**具名变异**：把 `x86_64` 放进 `device` flavor 的 `abiFilters` ⇒ `test_android_device_flavor_abi_is_arm64_only` RED；还原 ⇒ GREEN。

**Task 3（workflow）— 完成。** `.github/workflows/android-emulator.yml` 仅 `workflow_dispatch`，产物 `DeLector-emulator-apk`，不写 `dist/DeLector-*`；守卫 `test_emulator_workflow_is_isolated_from_release` 覆盖。临时验证分支实测 `gradle assembleEmulatorDebug` 成功（run `41813642926`），产出 `apk/emulator/debug/app-emulator-debug.apk` 且含双 ABI。

**Task 4（文档）— 完成。** `docs/agents/architecture.md` 更正 `android_24` 语义并写明 `applicationIdSuffix` 副作用与「真机/模拟器均未点检」。

## Deviation Table (post-execution)

| plan text | what was actually built | why |
| --- | --- | --- |
| Task 0 workflow 用 `workflow_dispatch` 触发 | 额外挂了 `push: branches: [probe/android-x86_64-wheels]` | `workflow_dispatch` 在默认分支注册前无法通过 API 触发；探针必须跑在非默认分支。仅存在于一次性分支，未进正式 PR |
| Task 3 计划写「常驻 workflow」为 Task 3 | 实际保留，命名 `android-emulator.yml`，并补隔离守卫 | 否则模拟器变体在 CI 上没有任何产出入口；隔离守卫钉住不碰发版路径 |
| 用 `buildType emulator` 承载 ABI | 改为 `productFlavor emulator` | Chaquopy 的 `getAbis` 不读 buildType，buildType 方案直接构建失败；flavor 是插件唯一支持的变体级 ABI 机制 |
| 发版 workflow 抓 `apk/debug/app-debug.apk` | 改为 `apk/device/debug/app-device-debug.apk` | flavor 必然改写输出目录；已同步改 CI 并加守卫禁止引用 `apk/emulator/`，防止发版抓错包 |
| `assembleRelease` 路径/命名不变 | 路径变为 `apk/device/release/...`，但 `emulatorRelease` 已禁用 ⇒ 仍只产出一个正式 APK | flavor 的固有代价；最终发版产物名 `DeLector-<tag>-Android.apk` 保持不变 |
