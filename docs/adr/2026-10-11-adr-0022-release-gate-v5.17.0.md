# ADR-0022 · v5.17.0 发版门与搁置边界（首发原生桌面壳 + 首次数据落点外置）

> **决策者:** Haoyu Xi ｜ **产出方式:** `/dfs-grill` 双镜拷问（Product & UX 席 + SRE 席并行）+ 用户拍板。
> **状态:** 已决策并落地前置项（守卫①②与 README 处理）；**发版本身待执行**（`/dfs-release`）。

## 1. 背景 (Context)

用户提问：*「现在值得发版吗？这些小的先不进行修改？」*

**事实（本次实测/核对，非引述）**：最近 tag `v5.16.0`（`90f62a3`，2026-10-06）；master 上**未发布提交 108 个**；版本面三处（`delector/core/version.py:15` `APP_VERSION`、`static/index.html:40`、`static/sw.js:3` `CACHE_NAME`）仍停在 5.16.0。

**提问前提被纠正（关键）**：本版真正的载荷**不是**"几条小修"，而是 ——

| 首发项 | 证据 |
| --- | --- |
| **原生桌面壳（pywebview）** | `git cat-file -e v5.16.0:desktop.py` ⇒ **不存在** |
| **数据落点外置 + 一次性迁移** | `git show v5.16.0:start.py` 调 `bootstrap_data_dir` **0** 次；当前 **3** 次 |
| **打包入口切换** | `v5.16.0` 的 `package_windows.py` 无 `DEFAULT_ENTRY`；当前 = `"desktop.py"` |
| 更新 chip | `ee68ec8` 无任何 tag 包含 |

另：那 6 条用户可感知修复（错高亮 / 列表 918→8.9ms / 首屏少 383KB / 四条 P0 / 难度跳变）**已装用户拿不到** —— `static/` 内嵌在产物里，必须重下新产物。

## 2. 决策驱动 (Decision Drivers)

- **用户侧**：① 不发版 ⇒ 上述修复对已装用户**零受益**，且 `System · vX.Y.Z` 版本指标失真；② 公开 README 有两处会主动误导用户的失真（数据落点、WebView2 前置）；③ 更新 chip 需要一个"更晚的 release"才有可演示对象。
- **技术侧**：① 首发新壳 + 首次迁移是**CI 两个盲区** —— 打包侧取版本"tag 优先"却**无 tag↔`APP_VERSION` 绑定断言**；真启包闸**强制设 `DELECTOR_DATA_DIR`**（`tools/verify_windows_portable.py:585`，注释自称 MUST）⇒ **绕开真实迁移路径**；② 回滚代价不对称（数据迁移近似不可逆；Android `versionCode` 只能升）。
- **成本侧**：两条守卫都**不碰运行代码**、量级十几行。

## 3. 考虑过的选项 (Considered Options)

| 选项 | 内容 | 取舍 |
| --- | --- | --- |
| **A** | 原样搭车发（2s 与 D1 只记 known-issues） | 最省时；但把两个"CI 看不见"的盲区直接交给真机 |
| **B** ✅ | **先补两条守卫 + README 修正，再发** | 成本小、把盲区变可见；发版晚一小段 |
| **C** | 先切 prerelease 给少数人真机验壳 + 迁移 | B 的时间兜底（`build-release.yml` 支持 prerelease） |

两席结论**曾冲突**：Product 席 ➡️"发，就现在（补三条用户可见声明）"；SRE 席 ➡️"原样不推荐（先补两条守卫）"。**收敛**：两席其实共享同一前提（"本版赌注是首发新壳 + 首次迁移"）⇒ 先花小钱把赌注变成**可验证**，再发。

## 4. 决策 (Decision Outcome)

- **Q1 = B**：先补两条守卫 + README 修正，**再发版**。
- **Q2 = B**：搁置清单**全部保留**（含 Defender 扫描不做），但**必须以 known-issues 明文进发版说明**两条 —— ① 那 2s 端口/身份校验是**本版新引入**的显式校验（冷启动 ~6s 含它）⇒ **发行说明不许拿它当提速卖点**；② **D1**（三句柄并发追加 `launch.log`，Windows 实测丢整行 ≈3%）⇒ `tools/first_screen_from_log.py` 报退出码 3/5 **不必然**等于日志损坏。

## 5. 实施状态 (Implementation, 2026-10-11)

**守卫①（已落地）：tag 必须等于 `v` + `APP_VERSION`** —— `package_windows.py::assert_tag_matches_app_version`，接线在 `resolve_version()`；真 tag 语境不一致 ⇒ **构建期硬失败**（预发布尾缀 `-rc1` 放行）。5 条新用例 + 2 条变异自证（摘接线 / 去预发布放行 ⇒ 均红）。

**守卫②（形式被改写，如实记录）** —— 原提案"真启闸加真实迁移路径变体"。勘察**真实产物**后发现：`_internal/delector/` 下**只有 `data`**（无 `__init__.py`、无 `core/`；纯 Python 模块在 PYZ 里）⇒ `_package_root()` 的「向上走到没有 `__init__.py`」**一次都不执行**，返回 `dirname(__file__)` = **`<pkg>/_internal/delector/core`**。
⇒ **"旧落点"既不是程序目录也不是 `_internal`**，那个变体的**播种目录**本身需先定案 ⇒ 本轮降级为**语义钉**（monkeypatch `__file__` 模拟冻结布局，钉住 `legacy_data_dir()` 的实际取值）+ 发版清单里一次**人工"覆盖安装"冒烟**。覆盖安装场景仍成立（旧库与新包在同一相对位置 ⇒ 迁移命中）；换新目录解压则无可迁（与 v5.16.0 行为一致）。

**连带改写的 3 条既有用例**（修守卫会牵连依赖它的用例）：两条用 `v9.9.9` 当 tag 的改用**预发布 tag**（唯一"既合法又与回落值不同"的形态 ⇒ 保住"tag 优先"的判别力）；一条"tag 含非法分隔符经净化"重构为**直测 `sanitize_version()`** + 新增"守卫①优先级"用例（历史事故面 `128/merge` 另有独立用例覆盖）。

**README 健康处理（已落地）**：去掉个人 Obsidian Vault 路径（隐私）；纠正数据落点与 WebView2 前置；测试模块数 60+ → 117；裁掉与 CHANGELOG 重复且与上方矛盾的旧版本摘要；新增「⚠️ 已知限制」承载上面两条 known-issues。

## 6. 后果与登记 (Consequences)

**已确认的既有风险（发版前必读，未在本轮修）**
- **R2 Android 不可回滚**：`versionCode` 只升不降 ⇒ 一次坏发布只能"卸载重装"。
- **R4 Release 说明与 CHANGELOG 脱节**：`build-release.yml` 的 release body 是**写死样板**、不读 CHANGELOG ⇒ 发版时需人工补 known-issues 段。
- **R5 端口探针是无界调用**：`start.is_port_in_use` 的 `connect_ex` **无 timeout / 无重试 / 无熔断**（对照：`server_lifecycle._fetch_health` 有 `timeout_s`）；某机 SYN 重传更狠时可拖到 OS 级 TCP 超时。
- **Defender 扫描**：按 Q2=B **搁置**（数据已外置 ⇒ 即使包被隔离也不再连库消失，风险低于 ADR-0020 §5 写作时）。

**递延（挂账）**：那 2s 端口探测（环境嫌疑未定案，三步可逆恢复法见 ADR-0018 §8）、B-3（全局钉 `DELECTOR_DATA_DIR` 需先改两条默认路径守卫）、远端残留分支、P2 批次 D1–D7。

**未闭合**：发版本身（版本面三处 bump + CHANGELOG 追加 + tag + 产物 + Release 说明的 known-issues 段）—— 交 `/dfs-release`；`Windows Portable Smoke` 在**首个桌面壳正式版**发 tag 前应在**同一 commit** 手动 `workflow_dispatch` 跑一次。
