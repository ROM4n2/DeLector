# DeLector 运维与安全（Agent 深读文档）

> 2026-09-05 从 `AGENTS.md` 拆出；维护约定同 `architecture.md`。

---

## 安全与提交守卫

- **pre-commit 密钥扫描**：`.githooks/pre-commit`。**`core.hooksPath` 是本地配置，不随 clone 生效**，
  每个克隆都要手动开一次：

  ```bash
  git config core.hooksPath .githooks
  ```

  覆盖 8 个 key 家族（OpenAI/Anthropic、AWS、GitHub PAT ×2、Google、Slack、JWT、私钥 PEM）
  与密钥文件名（`.env`、`*.pem`、`*.secret`、`*credentials*`、`id_rsa*`、`id_ed25519*`；
  `.example`/`.sample`/`.template` 放过）+ **PKCS12/JKS/JCEKS 编码 keystore 拦截**
  （文件名 `*.p12/*.pfx/*.jks/*.b64` + 内容中 PKCS12/JKS/JCEKS base64 特征，`.example`/`.sample` 放过）。
  扫的是**暂存文件全文**而非 diff 新增行，
  因为按行 diff 会漏掉"把含密钥的行挪到另一个文件"。
  误报走行内 `delector:allow-secret` 注释（豁免留在 diff 里可被审阅）；
  **不要用 `git commit --no-verify` 跳过**。

- 真实 key 走环境变量或 `.env`（已 gitignore），绝不硬编码。
- `POST /api/settings` **仅回环可写**（v4.4.0）：`GET /api/settings` 保持可读；敏感字段写入与
  `POST /api/settings/test-key`、备份相关 ` /api/backup/*` 均要求 `127.0.0.1`/`::1`
  （含 IPv4-mapped 回环），局域网返回 403。这是 Android 只绑回环的延续；桌面端仍绑 `0.0.0.0`
  保持同 Wi-Fi 阅读能力，但局域网不得修改敏感设置。

---

## 本机开发环境

```text
启动命令:  python start.py   或   start.bat
地址:      http://localhost:8000（桌面端同时绑 0.0.0.0，同 Wi-Fi 设备可访问；敏感设置仅回环可写）
数据库:    D:\Code\DeLector\delector.db（主库）
           D:\Code\DeLector\progress.db（进度）
NLP 模型:  优先 de_core_news_md，缺失则 de_core_news_sm（本机装的是 sm）
测试:      pytest            （719 passed + 1 skipped，全绿）
行为探针:  node tools/<name>.mjs（10 个，发布闸要求 10/10 全绿，含 wb_queue_probe 13/13 切片护栏）
打包:      python package_windows.py（Windows 便携版）；Android: cd android && ./gradlew assembleDebug
静态检查:  ruff check .       （全仓零告警门禁，CI 的 ci.yml 已接入；旧的手工 pyflakes 命令已退役）
```

**Git 推送通道**：这台机器上 HTTPS 连 fetch 都会失败（`schannel: failed to receive handshake`），
`origin` 已指向 `ssh://git@ssh.github.com:443/ROM4n2/DeLector.git`（22 端口时通时不通，443 稳定）。
`gh` CLI 走自己的 HTTPS API 认证，不受影响。

---

## 内容分发：桌面 → 手机（WiFi 拉取）

遇见区的卡包分发是**手机拉取**模型，**不是桌面推送**。原因：`start.py` 中 Android 实例有意绑
`127.0.0.1`（绑 `0.0.0.0` 会把无鉴权的 `POST /api/settings` 暴露给局域网），所以手机不可被外部
访问；而桌面绑 `0.0.0.0`，天然是局域网里的「货架」。

流程（同一 WiFi 下）：
1. **桌面产包并落本机**：`delector job run encounter-pack --corpus-dir <语料目录> --deliver-to http://127.0.0.1:8000`
   （`--deliver-to` 走既有 `POST /api/encounter/import-pack`，按 `pack_id` 幂等；重复投递不产生重复行）
2. **拿桌面地址**：`GET /api/wb/lan-info`（返回本机私有 IPv4），或看背词同步面板展示的地址
3. **手机导入**：遇见区 → 「📥 从电脑导入」→ 填 `http://<桌面IP>:8000` → 连接电脑 → 选包导入
   （地址记忆在 `localStorage` 键 `enc.desktop.v1`，下次自动回填）

安全边界（MUST，勿"顺手放开"）：
- 桌面货架 `GET /api/encounter/packs` / `GET /api/encounter/packs/{pack_id}` **只读、局域网开放**
  （与 `GET /api/wb/state` 同级的"拉取免 key"纪律），**绝不提供写操作**；列表响应只含
  `pack_id/title/level/word_count`，不含 `pack_json`/正文。
- 手机写路径一律挂 `_require_localhost`（`POST /api/encounter/pull-pack` 亦然）；**出站由手机服务端完成**，
  前端只调本机相对路径（同源零跨域）——探针里有反例钉，禁止前端拼 `desktop_base` 直连桌面。

---

## Android 真机点检：听力微训 TTS 三模式

> 前置条件：**手机上必须装有包含听力微训的 APK**（当前需 v5.6.0 发版后覆盖安装，或本地
> `cd android && ./gradlew assembleDebug` + adb 安装；Android 是独立实例，static 打包在 APK 内，
> master 已合入的功能不会自动到达手机）。建议联网（Edge TTS 兜底需网络；Native TTS 免网）。

TTS 链路（真机判定层）：`AndroidNativeTTS.speak`（系统 TTS，免网）→ `POST /api/audio/tts`
（Edge TTS，`services/tts.py` stdlib 客户端，需网络）→ `speechSynthesis`（WebView 兜底）。

**点检项（三模式各跑一个短会话）：**

- **Mode L 精听/影子跟读**
  1. 选材料 → 播放 → 逐句出声，当前句高亮与播放同步
  2. 变速 0.75x / 1.0x / 1.25x 切换即时生效；上一句/下一句/重复正常
  3. 跟读停顿：播放后停顿数秒再进下一句（shadow 模式）；切「连续」无停顿
  4. 三层全失败（飞行模式 + 系统无德语引擎）：停止并显示「⚠ 语音引擎不可用」，不空转
- **Mode D 听写**
  5. 隐藏原文 → 逐句播放 → 输入 → 提交 → 六色胶囊反馈（correct/umlaut/case/inflection/missing/extra + hint）
  6. 逐句推进；会话结束成绩卡出现
  7. diagnose 为本地比对（免网）——飞行模式下应仍能提交判分
- **Mode C 填空**
  8. 挖空渲染（`___` 占位）→ 播放 → 输入 → 大小写/变音容差校验
  9. 短句（<5 词）不挖空；成绩计入会话

**记录纪律**：逐项记「期望 vs 实际」；异常抓 `adb logcat -s TextToSpeech` 或 WebView 控制台。
发现缺陷 → 记入 work.log 并在下个补丁回合修复（PWA 类修复须发 patch 才能到用户手机）。

---

## Agent 工作惯例

1. **先验证再断言**：声称"已修复/已完成"前先跑验证并给出证据（复现脚本、测试输出、
   拆包核对）。本项目的失败模式大量是**静默降级**，"看代码觉得对"经常是错的。
2. **改 Android 相关代码前**：先读本文件姊妹篇 `docs/agents/architecture.md` 的「Android 独立单机版」一节。
   那里每一条都有代价，`python version` / `minSdk` / spaCy 版本 / `extractPackages` 改错都不会报错，只会静默退化。
3. **改标注/切句逻辑前**：确认改的是 spaCy 路径还是纯 Python 降级路径，两条都要过。
   切句只有 `syntax_tree.split_sentences_pure_python()` 一处实现。
4. **改 JS 前**：新增函数要在文件末尾 `window.xxx = xxx` 显式导出；
   不要用 `innerHTML` 插入含用户数据的原始字符串（用 `esc()` 转义）；
   不要把答案或敏感数据写进 `data-*` 或 `localStorage`。
5. **改后端路由前**：查看 `server.py` 顶部 `init_db()` 了解完整 schema；
   `app.mount` 必须在文件最末尾；**不要在模块顶层加可能抛异常的逻辑**。
6. **新功能测试**：在 `test_server.py` / `test_syntax_tree.py` 补测试，`pytest` 全绿。
   配置类约束也可以写成测试（例：有个测试直接读 `build.gradle` 断言
   `extractPackages` 列了那三个包）。
7. **提交前**：`git diff --stat` 确认范围合理；绝不提交 `.env`、`*.db`、APK 等产物；
   pre-commit 钩子必须启用且不绕过。
8. **每次 git 推送必须同步更新版本面（MUST）**：发版/修复涉及版本号、特性、测试数、
   目录结构任一变化时，对应落点要同一提交内更新到位（Release badge、下载表版本与 release
   链接、Tests badge、核心特性摘要、技术栈测试数、目录结构）。**版本历史与发版 changelog 的
   正主（single source of truth）是仓库根的 `CHANGELOG.md`** —— 发版五件套中的版本历史落点为
   **④ `README.md`（badge + 下载表 + 最近 3 版摘要）与 `CHANGELOG.md`（追加本次版本条目 —— 版本
   历史正主）**：`README.md` 是入口只留 badge 与最近 3 版摘要的指针，完整历史一律指向
   `CHANGELOG.md`，**绝不在 README 复制第二份**（DOC-GOVERNANCE 单一真相源）。不要等发布后再补
   ——README 是仓库门面，滞后会让用户/协作者看到与代码不一致的版本。
9. **大改动后**：更新 `WORKMEMORY/PROJECT_OVERVIEW.md` 的「当前状态」「红线速查」「开放待办」；
   发布类变更在 `CHANGELOG.md` 追加版本条目（**升序：接在最新版本条目之后**，版本历史正主），README 只留最近 3 版摘要与指针。
10. **缓存问题**：**不要再用 `?v=X.X.X` 查询串给 CSS/JS 打版本号**（v4.4.5 已退役）。
    它挡不住真正的问题，还制造了安全感：安卓覆盖安装后磁盘上那份文件本身就是旧的，
    请求 URL 与响应内容是一对自洽的旧配对；而 `main.js` 的 ES module import 全是裸路径
    （`./core.js` 等），从来就没被版本串覆盖过。现在两道真闸门是：
    - **服务端**：`server.py` 的 `add_frontend_no_cache_headers` 给 HTML/JS/CSS 发
      `Cache-Control: no-cache`（强制回源校验，靠 StaticFiles 已有的 ETag 命中 304；
      不用 `no-store`，那会禁掉全部缓存并削弱 PWA 离线能力）。
    - **安卓端**：`MainActivity.syncStaticAssets()` 按 `BuildConfig.VERSION_CODE` 比对
      `filesDir/static.version` 标记，不一致就删掉整个 `static/` 重解包。
      发版要 bump 的版本号有**三处**，`test_version_is_consistent_across_release_surfaces`
      会断言它们完全一致（改一处漏两处 = 测试红，不用靠记性）：
    - `static/sw.js` 的 `CACHE_NAME`（决定 activate 何时清旧缓存）
    - `android/app/build.gradle` 的 `DELECTOR_VERSION_NAME` / `..._CODE` fallback
      （`versionCode` = `major*10000 + minor*100 + patch`）
    - `static/index.html` 顶栏 `System · vX.Y.Z Online` —— **别把它当装饰**。
      它是用户唯一能肉眼判断「前端刷新了没有」的指示灯。v4.4.5 就漏了这一处：
      升级链路修好了，指示灯照旧报旧版本，于是"修复没生效"与"缓存闸失效"
      在现象上无法区分，最后只能靠拆 APK 才排查清楚。
      **指示器和它指示的东西必须被同一个断言绑住**，否则指示器本身会成为
      最贵的一类 bug —— 它不让任何测试变红，只让所有人对着正确的系统查错。
11. **用户报「前端修复没生效」：先判别代码陈旧 vs 用户运行时陈旧，再动码**（2026-09-08 桌面两报实证）：
    - 证据纪律：在浏览器里**走一遍用户的真实路径**取证（如 词库→编辑→弹窗逐按钮 DOM/`elementFromPoint`），
      不要只看代码"看起来对"就和用户来回拉扯。
    - 本项目的缓存叠层：在线时服务端 `no-cache`+ETag 强制回源、`sw.js` network-first，
      workbench 的 inline blob SW（`#sw-source`）是**死代码**——现代 Chrome 拒绝
      `register(blob:...)`（实测 `URL protocol of the script ... is not supported`）。
      ⇒ 服务端在线时磁盘新文件必被新页面加载；用户看不到修复，只剩两种运行时陈旧：
      ① 一直没关的旧标签页（跑着修复前的 JS，不刷新不变）；② 服务器没开时打开了
      「安装成 App」的离线窗口 → `sw.js` 离线兜底喂缓存旧页。
    - 判别法（先给用户做，不先改码）：F12 → 右键刷新按钮 →「清空缓存并硬性重新加载」；
      或开**无痕窗口**访问（无痕无缓存/SW = 服务器磁盘真实文件）。无痕正常 ⇒ 用户侧缓存，代码不用动。
    - 教训：别在 `setupPWA`/`#sw-source` 上花时间"增强"离线——那段 SW 从没注册成功过。

---

## Android 真机点检：长难句精读工坊（v5.7.0）

> 前置条件：**手机上必须装有包含长难句精读工坊的 APK**（当前需 v5.7.0 发版后覆盖安装，或本地
> `cd android && ./gradlew assembleDebug` + adb 安装；Android 是独立实例，static 打包在 APK 内，
> master 已合入的功能不会自动到达手机）。全程免网（句子分析走本地 spaCy/纯 Python 双路径 + 查词
> 走本地词典），飞行模式可用。

**点检项（跑一个 3–5 句的短会话）：**

- **入口与选源**
  1. 备考域出现「✍️ 长难句精读」带（与「🎧 听力微训」并列）；点进工坊默认选中一个材料源
  2. 选源切换 article / encounter / 全语料难度榜即时生效；级别默认 A2+ 门控，可切「全部」
  3. 无超纲句时出现空态提示（"没有超过当前难度的句子"），不崩面板
- **句子卡片流**
  4. 句卡按难度分降序排列；卡面显示原句 + 难度分 + CEFR 级别标签 + 维度 chips（从句深度/被动/虚拟式/VL 句框/长度）
  5. **先尝试拆解**：默认隐藏句法树（先自己找主句/从句）→ 点「揭示」后渲染 clause_tree/topology 与 VL 标注
  6. 逐词释义：点句内词弹查词抽屉（`/api/lookup/vocab`），本地词典离线可取义
- **降级标注（红线 1）**
  7. 纯 Python 降级句（`path="pure"`）显示「近似分析」提示，评分标注仅参考；spaCy 句（`path="spacy"`）无此提示
- **入复习盒 + 成绩落盘**
  8. 「加入复习盒」→ 写入 `grammar_cards`，句卡按钮变「已加入」；重复点不再重复入盒（幂等）
  9. 会话结束/退出时成绩落 `hard_sentence_trials`（可到复习卡域确认该句按 SRS 复习）；飞行模式下提交 trials 与入盒均应可用
  10. 顶栏「System · v5.7.0 Online」指示器与 APK 内前端一致（覆盖安装后确认已刷新）

**记录纪律**：逐项记「期望 vs 实际」；异常抓 `adb logcat` 或 WebView 控制台（前端报错看
`hard-sentences.js` 调用 `/api/syntax/*` 的响应）。发现缺陷 → 记入 work.log 并在下个补丁回合修复
（PWA 类修复须发 patch 才能到用户手机）。

---

## 存量富字段回填规范（MUST · 词表/精读生词同步）

> 2026-09-21 立规（源：A1 存量裸条目 `anbieten`/`allein` 排障 + A2/B1 与 reader 生词回填设计）。
> 适用于「服务端 / 上游 → 本地词表、精读生词」的**全部**同步路径（A1 首装合并、A2/B1 档同步、
> reader 生词同步）。跨项目正式规范：Coding Vault `01-Rules/STORED-DATA-BACKFILL.md`。

用户报「升级了还是旧的」时，**先怀疑存量记录被冻结，而不是数据缺失**——上游数据通常是全的。

1. **回填 MUST 发生在读取期（派生投影）**，MUST NOT 只靠写入期填充。写入期填充只覆盖未来：旧版本首次
   落盘的记录已被写死，此后上游补的字段永远进不来。`bootstrapA1Words` / `sync{A2,B1}CardsFromServer` /
   `syncReaderCardsFromServer` 都属读取期合并点。
2. **重复合并的闸门 MUST 按「能力」判定**（此刻上游是否可达），MUST NOT 按「历史来源标记」判定。
   反例（v5.9.1 及以前）：`if (!A1_BOOT_PENDING && lastSrc !== "inline") return;` → 已以 `server` 落盘的
   设备永不重新合并；正例（v5.9.2 起）：`if (!A1_BOOT_PENDING && !canUseServer) return;`。
3. **同步 MUST 只增 + 只补空 + 幂等**：已存在的词条 MUST NOT 被覆盖；仅补空字段；不碰 `cards`/`log`/`wrong`
   与手编内容；上游无新信息时 `changed === false` 且不写盘。append-only（`if (!has(id))` 且无 else）不满足本条。
4. **补字段 MUST NOT 跨语义来源混用**：同名槽位在不同来源可能语义不同——`de` 在 A2/B1 是「官方例句」，
   在 reader 生词是「该词所在原句」。既有值非空 → 保留原值（**原句优先 · 只补空**）；两种语义都要 →
   **另立字段**，不得复用同一槽位；也不得只补"半件"（德文原句 + 官方例句的中文 = 文不对题）。
5. **未命中 MUST 诚实留空**（不编造、不用默认值兜底）。提升命中率靠**归一化上游键**（小写、去冠词
   `der/die/das/ein/eine`、`lookup_irregular_verb` 兜底）与确定性查表，MUST NOT 靠降低诚实度。
6. **回归 MUST 是行为级探针**（`tools/*.mjs` 真实源码切片 + `node:vm` 真跑），断言五条：补空生效 /
   非空不被覆盖 / 用户数据零写入 / 二次运行零变化 / 标记不回退。静态断言不得替代（Coding Vault
   `01-Rules/TESTING-PATTERNS`）。

---
