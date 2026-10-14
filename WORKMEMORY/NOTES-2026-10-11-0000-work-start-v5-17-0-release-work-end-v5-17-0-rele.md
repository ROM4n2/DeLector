### 2026-10-11 | codebuddy | WORK_START(v5.17.0-release)＋WORK_END(v5.17.0-release)

> 本文件是 `WORKMEMORY/work.log` 中该事件的**正文**（原事件 4299 B，超 `PROTOCOL.md` §4 的 4096 B 上限）。
> 拆分时间：2026-10-14；正文逐行无损搬运，未删改任何内容。

Caps: filesystem-read, filesystem-write, shell-exec
事件：v5.17.0 发版全流程闭环（ADR-0022 Q1=B / Q2=B 落地）。tag `v5.17.0` → commit **`f359ea6`**；Release https://github.com/ROM4n2/DeLector/releases/tag/v5.17.0 四资产齐：Windows **85.8** MB / macOS **58.07** / Linux x64 **118.53** / Android **58.89** MB（取 Release 附件实测）。
- **版本面（commit `40a9f88`）**：四处 bump（`APP_VERSION` / build.gradle fallback `51700` / `sw.js CACHE_NAME` / `index.html` 顶栏）；README（badge + Tests **1223/1224 → 1768/1770** + 下载表 + 最近 3 版，移除 v5.14.0 摘要）；CHANGELOG 追加 v5.17.0（含「已知限制」「回滚」段）；PROJECT_OVERVIEW 当前状态与基线。**bump 连带修两条写死字面量**：`test_app_version_source` 的字面量，以及 `test_without_github_ref_type_local_v_tag_is_adopted` —— 旧写死的 `v5.16.0` 会被**新发版门守卫**直接拒（改用预发布 tag 形态保住"tag 优先 vs 回落值"的判别力）。这正是该守卫设计意图的首次实战命中。
- **顺带（commit `e2812b1`）**：`FEATURES.md` 严重落后（`当前版本 v5.0.2`；版本历史止于 v4.7.0；与 CHANGELOG **重复两张表**；平台表挂 v3.10.0 产物名与 56.7 MB 旧体积）⇒ 补「十八 桌面形态、数据落点与更新可见性」「十九 背词工作台与统一池」；两张重复历史表收敛为一张「能力里程碑」+ 指针 `CHANGELOG.md`；路线图改真实在途项；修 531/660 → 552/691、APK 体积、开发入口补 `python desktop.py`。
- **发版红卡（本线程唯一真事故）**：首次 tag（`e2812b1`，run 38143313101）四平台里 **macOS 红**于 `test_cache_classification_matches_measured_relationship`：`assert 11000.0 == 10658.46 ± 319.75`；`Publish` 因 needs 四平台全绿而 skipped（**未误发**）。**根因＝容差口径错，不是 macOS 算错**：`cache_speedup` 只报 **2 位有效数字**（`_format_speedup` 的 `:.2g`；分母是微秒级 dict 命中，多打印一位即伪精度），2 位有效数字舍入误差**最坏 5%**，而用例写死 `rel=0.03` ⇒ **容差比被测报告的精度还紧**；Windows/Linux 只是首位数离舍入边界远才偶然全绿。修法 `f359ea6`：新增 `_half_ulp(raw)` 由**打印出的字符串本身**推半 ULP（`1.1e+04`⇒500、`1.23`⇒0.005），主断言改 `|报出值 − 实测比值| ≤ 半 ULP`；并加**源码级棘轮**禁止本文件再出现 `pytest.approx(..., rel=...)`（行为断言锁不住回退：改回固定百分比后本机照样全绿）。变异自证 2 条（bench speedup ×1.5 ⇒ 主断言红；塞入 `rel=` 调用 ⇒ 棘轮红，均复原 + md5 复核）。
- **验收**：删远端 tag 后重打在 `f359ea6`（用户批准；Release 从未生成、无人拿到该版本 ⇒ 同名重打无副作用），run **38144724706** 四平台 + `Publish GitHub Release` 全 **success**；macOS job 步骤逐项 success（含 `Run Tests`）。ADR-0022 要求的手动 `Windows Portable Smoke`（run 38143045303，在 `e2812b1`）**已绿** —— 但注意它**只构建 + 真启，不跑 pytest** ⇒ 覆盖不到这次红的那类测试缺陷（下一版可考虑让该 job 也跑一遍 `pytest -q`）。
- **Release 说明**：`build-release.yml` 的 body 是写死样板、不读 CHANGELOG（ADR-0022 R4）⇒ 已 `gh release edit` 补两段：「🖥️ 本版重点」（原生窗口 / 数据外置 / 更新 chip / 六条随版到达的修复）与「⚠️ 已知限制」（含 Q2=B 硬要求的两条：那 2s 端口/身份校验**不许当提速卖点**、`launch.log` 约 **3% 整行**丢失；另加 WebView2 前置、Android `versionCode` 不可回滚、数据落点勿删）。
- **门禁**：全量 **1768 passed + 2 skipped**；探针 **29/29**；`ruff` 0；mypy **87 + 121 + 4** files 零错误；前端契约闸 PASS + `tsc` PASS；`test_writer_mobile` 30 passed。
- **口径教训（同族）**：受打印/舍入影响的两个量比大小或比相等时，容差 MUST 由**精度**推导（不许凭手感给固定百分比）；且"只在特定机器复现"的缺陷**行为断言锁不住**，必须配源码级棘轮。

