### 2026-10-08 11:12 | codebuddy | EXEC(ADR-0017 实施) /dfs-exec 六任务全绿 + 编排者三次自查纠错

> 本文件是 `WORKMEMORY/work.log` 中该事件的**正文**（原事件 4522 B，超 `PROTOCOL.md` §4 的 4096 B 上限）。
> 拆分时间：2026-10-14；正文逐行无损搬运，未删改任何内容。

Caps: filesystem-read, filesystem-write, shell-exec
事件：按 `docs/plans/2026-10-08-android-update-check.md` 走 `/dfs-exec`，maker-checker 逐任务派单（implementer=CPE，checker=CRV），**5 个原子 commit**（分支 `feat/update-visibility`，未 push、未发版）：
`b2f191c` Task1 版本单一真相源 → `cf69bf2` Task2 版本面归一+守卫升级 → `efee426` Task3 端点 → `1acdcf7` Task4 契约守卫 → `051ed7d` Task5 前端 chip。
（Task6 为 HITL 收口，由编排者亲自执行）
- **交付内容**：① `delector/core/version.py`（`APP_VERSION` + `version_code()`，叶模块零 import）；② 两条发版守卫基准从"三面互等"升级为"每面 == APP_VERSION"，顶栏去掉误导词 `Online`；③ `GET /api/update/check`（GitHub Releases 唯一真相源，7 键契约，成功缓存 6h / **失败只 60s**，`threading.Lock`，**不挂本机闸**＝ADR-0017 §4.3 显式决定）；④ 端点契约守卫（穷举 iff 双向 + 结构证不写库 + 无本机闸）；⑤ 顶栏 chip（`static/js/update.js` + `tools/wb_update_chip_probe.mjs` 11 场景 + wrapper）。
- **checker 三轮抓到的高价值项（都不是"风格问题"）**：
  ① Task1 `part.isdigit()` 与 `int()` 定义域不重合 ⇒ 全角「５.１.０」**静默出数 50100**，与同函数 docstring 宣称的"绝不静默出数"矛盾（改 `isascii() and isdigit()` + 2 用例）；
  ② Task3 注释**在撒谎**：称 Lock"避免并发重复出网"，而锁**不覆盖出网**（并发首个 miss 各出一次）；
  ③ Task5 守卫盲区：静默快照原只覆盖 `#update-chip`，**运行期往自证串 `#topbar-system` 追加内容无守卫**（源码静态断言拦不住）⇒ 已纳入快照并变异自证（静默路径污染 → 4 条静默场景全红 failures=5）。
- **编排者退回 implementer 修的（不 inline 补，守 maker-checker 边界）**：模块级 `# mypy: disable-error-code`（编排者做**决定性实验**：摘掉后两条 mypy 仍 95/72 全绿 ⇒ 该豁免不必要，maker"仅 skip 模式误报"的判断被推翻）；注释声称三类 DB import 是"本项目**全部**入口"（被 grep 证伪：`services/search.py`、`core/vocab_pool.py` 各自 `import sqlite3`）。
⚠️ **编排者本轮三次自查纠错（全部如实记录）**：
  ① 任务书把"越权注释位置"写成 `delector/routes/update.py`，实际在**测试文件**（maker 正确停下并纠正，且严格只改测试文件）；
  ② 我的临时探针汇总 shell 脚本口径错（legacy 探针用 `fail` 键、标准形态用 `failures`）⇒ 误报一片 `NO-JSON`；改用 Python 双键解析重跑才拿到正确口径；
  ③ 缓存验证脚本**先 `_cache.clear()` 再调第二次**，几乎把 `cached=false` 误报成实现缺陷；自查后重做（连续三次：首调出网、二/三调 `cached=true` 且 `checked_at` 保持原值、TTL 21600s、计数出网 1 次）。
**门禁（feat 分支实测，数字来自本次最终 commit 的本人实跑）**：半 A **1106** passed（基线 1053 + 53 新增：Task1 16 / Task3+4 27 / Task5 10）；半 B `test_server` **264** passed + 1 skipped；`tools/*_probe.mjs` **29** 个文件（原 28 + 新增 `wb_update_chip_probe.mjs`，其中 12 个标准三键 + 16 个 legacy 扁平形态由 `test_probe_json_contract.py` 覆盖 + 1 个需参数的 `wb_a1_bootstrap_probe.mjs` 由其驱动测试传参）；`ruff check .` 0；mypy 两道 **96** + **72** files 零错误；探针 `wb_update_chip_probe` **11/11**。
**桌面侧真实出网验证（Fog Unknown 1 的桌面侧数据点）**：`_fetch_latest_release(3.0)` **成功**（4.04s，`tag_name=v5.16.0`）⇒ 本机到 `api.github.com` 的 TLS 通路可用；`check_for_update()` 真实返回 `has_update=false`（当前 = latest = 5.16.0，语义正确）。注意 `_HTTP_TIMEOUT=3.0` 是 **httpx 各阶段超时**而非总时长，实测总耗时 4.04s 仍成功 —— 记录以免将来误判。
**仍未验证（Fog of War，需真机）**：① Android/Chaquopy 上 httpx 能否完成到公网 `api.github.com` 的 HTTPS（`encounter.py:381` 的手机出网是 **LAN HTTP**，不能作为证据）；② Android WebView 点击 chip 外链是否被交给系统浏览器（若被吞需改 `MainActivity` 的 URL 拦截，而 Java 本机无法编译、只能靠 CI）。**Task 6 Step 3 因此仍阻塞**。

