# 更新日志 (Changelog)

> 本项目**版本历史的正主（single source of truth）**：每次发版在此追加条目。
> 桌面 / Android 四平台发布资产见 [GitHub Releases](https://github.com/ROM4n2/DeLector/releases)；
> 开发决策细节见 `docs/plans/` 与 Obsidian Vault `08-Projects/DeLector/01-ADR/`。

**最新版本：v5.9.4（2026-09-20）**

---

## 🗺️ 路线图 (Roadmap)

- [x] **v1.0**：德语文章分词、欧标高亮与词汇卡片库

- [x] **v2.0**：Gutenberg Broadsheet 学术社论设计系统重构与 Edge TTS 神经伴读

- [x] **v2.1**：3D 物理扑克卡盒、Leporello Folio 三折风琴学术台账、三大考验自测模式

- [x] **v3.0**：智能完形填空实战引擎 (Lückentext / C-Test) + SuperMemo SM-2 艾宾浩斯排程

- [x] **v3.2**：前端原生 ES Modules 模块化拆分 + 歌德 A1-B2 核心离线词库 (0ms 查词)

- [x] **v3.3**：权威德语外刊 RSS 一键订阅与正文提取 (Tagesschau, DW, DLF, Spiegel, Zeit)

- [x] **v3.4**：556+ 强变化三态表 + 复合词智能拆解 + 框形可分动词双向联动高亮

- [x] **v3.5**：德语拓扑五场域 (Felder-Modell) 与 5 大从句 AST 句法树引擎 + 全局设置面板 (deepseek-v4-flash)

- [x] **v3.7**：德语伴读宠物（Eule & 伙伴）+ 自定义 SVG 角色工坊 + 严格 DOMParser 递归消毒

- [x] **v3.8**：FSRS 现代自适应记忆排程器升级（DSR 三维认知模型，消除 Ease Hell，4 级下一轮间隔预计算）

- [x] **v3.9**：离线词库 443→4300 词（DeepSeek 批量生成中文释义）+ 查词链 lemma 优先 / 形态学接线 / 现在时反查 / UX 诚实显示

- [x] **v3.9.1**：安卓真机修复——TTS 无声（stdlib 版 Edge TTS 客户端 `edge_tts_mini`）、倍速按钮点不到（移动端三行布局）、单词抽屉白色遮挡（55vh + 阅读区全宽）

- [x] **v3.10**：固定介词搭配（Verben/Adjektive + Präposition + Kasus）——数据集 **531 词条 / 660 条搭配**（AI 批量生成 + 人工 seed 兜底），查词抽屉第四张卡片逐条展示并可直接存成词汇卡；**备份改全量真往返**，堵住三处静默丢数据（含 API Key 被吞）；**安卓签名迁移**——CI 钉死 keystore + keytool 验签闸（显式 v1 签名），versionCode 编码规则修正（`major*10000+minor*100+patch`，修 3.10.0 与 4.0.0 撞车）

- [x] **v3.11**：**德语写作润色台 (Schreibwerkstatt)**——本地规则引擎（spaCy 上冠词/格位一致 + 介词支配格，零误报准则），行内下划线 + 侧栏纠错，错误一键存 Anki 语法卡（你的错误变成你的复习卡），essays 作文草稿库，CEFR 词汇估测，显式 AI 润色全文按钮；「按介词浏览」的独立矩阵视图留待后续（数据集已就位，零成本增量）

- [x] **v3.12**：写作台 IDE 化：句子级 diff 引擎 + AI 润色逐 hunk 并排审查 + `essay_versions` 类 git 快照管理 + 侧栏诊断/历史双 Tab 联动

- [x] **v4.0**：内联 IDE 编辑器（contenteditable + TreeWalker 光标记忆 + 400ms 实时诊断 + 悬浮气泡 + 一键修正 + 句子导航）+ 版本管理完善（只读预览不产生检查点 + 单项删除）+ 动词固定介词优先

- [x] **v4.1.1**：VSCode 级真实 Inline Inlay Hints（CSS `::before` 伪元素无 text node + 随文本推开 + TreeWalker 纯净正文 0 污染）

- [x] **v4.2**：Problems 问题清单面板（severity 分级 + 双格介词 warning + 联动定位/高亮/修正）

- [x] **v4.3**：Android/移动端写作台适配（bottom-sheet、触屏纠错、Android 默认关闭 Inlay Hints）+ **安全加固**：存储型 XSS 全量修复（`jsAttr`）、SSRF 加固、TTS 长度闸

- [x] **v4.4**：**可靠性与安全收口**——敏感设置/备份仅回环可写（局域网 403）、pre-commit 编码 keystore 拦截、CI 真 Gradle 构建与验签闸、写作零误报加固、备份/AI 失败回归；测试 **230 全绿**，仅 14 条 linguistics 重复键既有告警；词库 110 词缺口盘点（30 缓存待合入，80 需 API，401 暂缓，不伪造）

- [x] **v4.4.5**：**安卓升级后前端不更新根治**——覆盖安装不清 `filesDir` 而解包逻辑见文件已存在即跳过，旧前端永不被覆盖、新增文件却照常拷入，设备停在「新旧混合」状态（此前只能卸载重装）；改为按 `versionCode` 比对标记文件决定是否整目录重解包，删除范围硬编码校验以确保用户学习数据不受影响。缓存闸移到服务端 `Cache-Control: no-cache`，退役从未真正生效的 `?v=` 查询串与 `sw.js` 死清单。**写作台三 Tab 交互统一**：整行点击 = 定位/预览，行内按钮 = 破坏性操作，结果落在编辑器时自动收起移动端面板；测试 **238 全绿**

- [x] **v4.4.6**：**修顶栏版本指示灯** + **移动端写作台面板位移/底部滚不到根治**——v4.4.5 漏 bump `index.html` 顶栏 `System · vX.Y.Z Online`，使修好的升级链路看起来像没生效（拆 APK 验证：包内 `sw.js`、`writer.js`、去掉 `?v=` 的 `index.html` 全是新的，只有那一句字面量是旧的），版本自洽测试纳入该标签；移动端 `.writer-sidebar` 用 `position: fixed` + `bottom` 锚点却只给 `max-height`、没 `top` 也没 `height`，高度跟内容走而盒子锚在底边只能向上长 —— 切 tab、填错误卡、清单从空变 N 条都把顶边挪到新位置（三个 Tab 都在跳，诊断分析跳得最狠），改用 `height: min(76vh, 680px)` 固定几何；内层三个列表（220/460/320px）原本各自开滚动区在 600px sheet 里几乎占满可见区域、吃掉外层滚动，统一 `max-height: none; overflow-y: visible` 归 sheet 一人管；`.writer-pane` 补 `flex-shrink: 0` 防父容器压扁。测试 **239 全绿**

- [x] **v4.4.7**：**桌面端侧栏几何收口 + 三行触屏按压反馈**——v4.4.6 移动端修复的同族另一半：`.writer-sidebar` 基规则 `position: sticky; top: 4.5rem` 在 `align-items: start` 的 grid 列里高度跟内容走，既无 `max-height` 也无 `overflow-y`，内容一长就整列溢出、底部永远滚不到；改为内部滚动 + tab 条吸顶。三种可点击行（错误卡/清单项/版本行）补 `:active` 按压反馈——触屏没有 hover，此前按下去毫无回馈。测试 **242 全绿**

- [x] **v4.4.8**：**离线词库补齐 + SSRF 闸判定修正**——① 两处「AI 始终不作答」其实**AI 每次都答了**：提示词要求反身动词 `wort` 不带 `sich`，匹配器却按 `lemma not in asked` 把返回值丢掉；单词请求会让模型「纠正」成词元（问 `zustände` 答 `Zustand`）而词库按表层形查，于是任何屈折形必然连丢 3 轮。改为把答案回映射到请求键：搭配 **531/660 → 552/691**（零 API 花费），词库尾缺口 **110 → 0**。刻意不做变音折叠——`drucken`/`drücken` 会互相领走搭配，**张冠李戴比漏检更糟**。② SSRF 闸拿**外层 IPv6 旗标**判定，而 IPv4-mapped/6to4/Teredo 的真实目的主机是**内嵌的 IPv4**：`2002:c0a8:0101::1` 外层 `is_global` 为真却路由到 `192.168.1.1`（旧写法一路放行），而 Teredo 落在 `2001::/23` 私有段清单里使开着隧道的 Windows 用户 URL 导入对所有站点全废。③ **首次打 tag 时 CI 红、Release 没发出去**：新加的那条断言在本机靠 `ipaddress` 私有段表一条粗粒度的 `2001::/23` 条目**顺手兜住**才绿，CI 的 Python 换成细粒度条目后 `2001:20::/28` 掉了出来 —— 同一个 3.11 大版本、判定相反。改法是自己钉住那些段，不是删断言。测试 **266 全绿**

- [x] **v4.4.9**：**按钮 token 体系补全 + 移动端 sheet 闭合态几何修正**——`.btn-xs` / `.btn-del` / `.btn-secondary` 三条规则**从未在 CSS 里定义过**而模板里到处在用，无声降级成裸 `.btn` 尺寸配色（删除类按钮和主按钮长得一样）；补齐并分出 `--danger` token。移动端 sheet 闭合几何 `bottom: 4.75rem` 抬起 76px 而位移只推走「自身高度 + 16px」，**差额 60px 的条带永远留在屏幕内**盖住底部 dock，改为 `bottom: 0` + `translateY(100%)` 与 reader drawer 同构。另加全仓库 dict 字面量重复键棘轮。测试 **280 全绿**

- [x] **v4.5.0**：**Präpositionen-Matrix 介词矩阵视图**——把 552 词 / 691 条搭配**倒过来**按介词分组（21 组，按搭配数降序），Dat/Akk/Gen 过滤 + 防抖子串搜索 + CEFR 标签 + 逐条一键入卡盒。分层上纯函数内核**不认识 CEFR**（会成循环导入），CEFR 注入与组排序留在服务端。⚠️ 本轮变异验证抓到**三条空转断言**：组内排序断言在数据本身有序时删掉 `sort` 也绿、payload 字段名在别处到处出现、端点测试两端读同一份缓存对象导致比较**恒真** —— 分别改为喂乱序输入 / 切进函数体逐字段断言 / 从数据集直接构造期望多重集。测试 **298 全绿**

- [x] **v4.6.0**：**德语背词工作台集成 + 手机端无声根治**——684 词单文件工作台（FSRS-6 / 卡片复习 / 自测 / 统计 / 词库）以 iframe 嵌入而非合并代码：同源共享 localStorage 与 `/api/`（零 CORS），同时与主应用 2449 行强耦合全局 JS 完全隔离。**移动端无声的两个根因**：`file://` 下 Web Speech 被协议禁掉 + 设备没装德语语音包；修法是新增 `GET /api/audio/tts`（服务端 edge-tts）并设为最高优先级音频源。⚠️ 两处 CSS 陷阱：`body` 的 `padding-bottom` **不在** **`.view`** **的 flex 高度链里**，fixed dock 会直接盖住填满视图的 iframe（移动端必须显式扣掉 nav + dock 高度）；裸 `#view-german { display: flex }`（特异性 1,0,0）会压过 `.view { display: none }`（0,1,0），显示规则**必须** `.active` 作用域。备份覆盖 `wb.*` 进度键。测试 **314 全绿**

- [x] **v4.6.1**：**背词台 TTS 修复：点一下不出声、再点一下读两遍**——两个独立成因叠在一起。① 入口清理在 `removeAttribute('src')` 之后多调了一次 `load()`，这会给 `<audio>` **排一个异步 error 事件**，它在当前同步块跑完后才派发，正好命中同一 tick 里刚装上的 `onerror` —— 首次点击被自己的清理判成失败而静默无声。② `_ttsAudio` 是两条链路共用的**全局单例**，per-attempt 的闭包标志管不住**上一次**尝试的回调：旧 timer 醒来会清掉新播放，旧 `onplaying` 又把新尝试判成已完成 —— 连点于是交叉干扰、重复出声；改为全局递增的 `_ttsAttemptId`，stale handler 自己认出该退出。**教训：共享媒体单例上，per-attempt 的闭包标志不足以做互斥，需要一个全局的 attempt 身份。** 测试 **316 全绿**

- [x] **v4.6.2**：**卡盒交互修复 + 伴读宠物 + 自测范围**——① 伴读宠物在背词台视图自动隐藏（不盖住设置按钮）；② 自测新增「复习不认识（评过 Again）」范围，`addWrong` 写入 `rv` 标记；③ 卡盒翻转 onclick 从容器移到正面，背面评分按钮加 `stopPropagation`，Android 3D 变换下不再误触翻转；④ `toggleDeckFlip` 加 200ms 防抖，阻断 Android 双击事件抖动导致的「翻了又翻回来」。测试 **316 全绿**

- [x] **v4.6.3**：**工作台导出 Android 修复 + 卡盒背面 swipe 拦截**——工作台用 `Blob + URL.createObjectURL + <a download>` 导出备份，但 Android WebView 的 DownloadListener 对 `blob:` URL **永不触发**（无报错，用户以为成功了）。改为走服务端下载通道：`download()` 先 POST 到 `/api/wb/backup/prepare` 换 token，再 `location.href` 到 `/api/wb/backup/download/{token}`（跟主应用备份同款机制），独立打开 HTML 时无 `/api/` 则走 blob 兜底。服务端新增 `/api/wb/backup/prepare` 和 `/api/wb/backup/download/{token}` 两个端点。② **卡盒背面评分按钮被 swipe 吞掉**：`attachDeckSwipeListener` 绑在整个卡片容器上，背面按钮的触摸也被捕获，手指轻抖就超 70px 阈值触发 `stepDeck`。改为 `deckFlipped` 时跳过 `onTouchMove` / `onTouchEnd`。测试 **316 全绿**

- [x] **v4.6.4**：**介词矩阵已入卡持久化**——新增 `prep_saved` 表（主键 `(lemma, praep, kasus)`）与 `GET/POST /api/prep/saved` 端点，前端 `_prepSavedKeys` 从服务端初始化（不再空 Set 起步），`savePrepCardFromMatrix` 成功后异步写入。备份/恢复带上该表。测试 **319 全绿**

- [x] **v4.6.5**：**局域网同步 6 位短码**——WebRTC P2P 同步的 SDP 传递从复制粘贴 2-3KB 文本改为 6 位短码：A 存 SDP 到服务端拿到 `K7M2X9` 大字码，B 输入取出 SDP，生成回执后同样拿到短码。`POST /api/wb/sync/store` + `GET /api/wb/sync/fetch/{code}`，内存缓存 5 分钟 TTL，一次性消费。测试 **322 全绿**

- [x] **v4.7.0**：**歌德 A1 备考工坊全面落地 (Goethe-Zertifikat A1 Werkstatt)**——702 官方考纲词汇（15 大真实主题、全量地道例句、准确复数、0 模板句）+ 8 套填表真题 (Schreiben Teil 1) + 10 套短电邮工坊 (Schreiben Teil 2 导向点诊断与满分范文) + 口语 Teil 2/3 考场题卡 + 3D 纸牌堆叠控制栏居中与响应式 UI 抛光。测试 **350 全绿**

- [x] **v4.7.1**：**修复安卓交互全死回归**——v4.7.0 模块化拆分把 `a1_cards.js`/`a1_writer.js` 以空文件提交，`cards.js`/`writer.js` 具名 import 导致 ES module 链接期 SyntaxError、整个模块图失败（`main.js` 永不求值，全 App 只剩 CSS 点击效果）。复原两空模块 + 补抽取后悬空引用 + 新增 `test_frontend_module_graph.py` 模块图结构性回归测试。测试 **352 全绿**

- [x] **v4.7.2**：**修复安卓卡片段标签栏被裁切**——5 个段按钮合计约 527px 超出一屏，被 `.view` 的 `overflow-x: hidden` 移动端守卫裁掉，最后的「歌德 A1」tab 不可见；改为移动端媒体块内 `.cards-seg-bar` 自身 `overflow-x: auto` 横滑到达（桌面内容列较窄，滚动规则必须 scoped 到移动端避免裁桌面 A1 右缘）。测试 **353 全绿**

- [x] **v4.7.3**：**修复 Android 16 导出下载失败**——`DownloadManager.enqueue()` 在 Android 16 上同步抛异常被 catch 吞成 Toast；且备份 token 原为「单次有效」，WebView 嗅探 Content-Disposition 的预取 GET 会烧掉 token，第二次 GET 拿到 404 错误 JSON 被静默存成「备份」。修法：弃用 DownloadManager，新增 `ExportSaver.java`（HttpURLConnection 自取 + MediaStore.Downloads 零权限落盘 + `{"detail"` 错误体内容自检）；后端 token 改为 10 分钟 TTL 内可重复取（`_issue_pending`/`_take_pending`），四个下载端点统一走 `_attachment()` 助手（Content-Disposition + no-store）。另含 pre-commit 密钥扫描性能优化。测试 **359 全绿**

- [x] **v4.8.0**：**歌德 A1 听力与阅读全真考场工坊 (Goethe A1 Hörverstehen & Lesen)**——① **听力考场工坊 (Hörverstehen)**：5 套官方标准试卷 (75 题) 覆盖日常对话 (Teil 1, 放2遍)、公共广播 (Teil 2, 仅1遍)、电话留言 (Teil 3, 放2遍)；考场流程状态机、25.0 换算得分评级、双语 Transkript 复盘与考点生词一键入盒；② **阅读实战工坊 (Lesen)**：6 套官方全真试卷 (90 题) 覆盖便条邮件 (Teil 1, R/F)、网页广告双选比对 (Teil 2, A/B)、公共标牌告示 (Teil 3, R/F)；25 分钟全真倒计时与答题卡全景矩阵；③ **模块化与可靠性加固**：新增 `a1_hoeren_dict.py`, `a1_lesen_dict.py`, `routes_a1_hoeren.py`, `routes_a1_lesen.py`, `a1_hoeren.js`, `a1_lesen.js`；会话令牌守卫消除异步竞态，`a1_hoeren_records`/`a1_lesen_records` 数据表与备份自动联动。测试 **367 全绿**

- [x] **v4.8.1**：**修复 Android 打包遗漏 6 个 Python 路由/语料模块**——Chaquopy 打包清单未纳入 `routes_corpus.py` 等 6 个模块，APK 启动时 import 失败导致引擎直接崩溃。补 hidden-import + APK 拷贝清单 + APP_NEEDLES 资产验证。

- [x] **v4.8.2**：**修复 Android 预设文章为空 + 首次进入交互无响应**——`server.py` 只建表未调 `seed_preset_articles()`，全新装无预设文章；且 seed 的 spaCy 冷启动阻塞在请求链上造成「前端版本号已显但交互无响应」感知。将 seed 移到应用构造阶段立即执行（count>0 不重复）。

- [x] **v4.8.3**：**修复安卓交互全死回归（`main.js`** **窗口回调未定义）**——`main.js` 底部 `Object.assign(window,{…})` 引用 `clearA1Email` 此名却已从 `from "./writer.js"` import 列表悄然删除，模块求值时抛 `ReferenceError`，整个回调挂载中断（无 handler 接线、仅 CSS 点击效果），页面照常渲染但点击无反应。`test_frontend_module_graph.py` 原先只验证「已 import 的名字能解析」，对这种「用了但没 import」的裸标识符看不见 —— 新增 `test_window_hook_exposer_identifiers_are_bound` 静态解析 `Object.assign` 块每个裸标识符、`test_writer_a1_email_functions_present_in_main_imports` 钉住 A1 helper 全量 import。测试 **373 全绿**

- [x] **v4.9.0**：**背词台核心词模式 + 导入按词头去重**——① **核心词模式**：235 词核心子集与 704 词全量一键切换，核心标记打在既有词条上而非复制词表（复制会分叉出两套 FSRS 卡），每日新词额度全局共享，复习途中切换只静默过滤**当前位置之后**的队列；老设备走幂等回填补 tag 并注入缺失核心新词，`S.cards`/`S.log`/`S.wrong` 一律不碰。② **导入去重**：`applyMerge` 原先只按 id 合并，同一个词在别的设备上是自定义词、在本机是内建核心词时会并排塞进词表 —— 两张独立 FSRS 卡、复习队列里同一个词出现两次；补归一词头二级索引。归一刻意**保留大小写、不带 pos**：德语里大小写承载语义，`sie`（她/他们）与 `Sie`（您）只差首字母且同为 Pron，`toLowerCase` 会把敬称并掉。③ 下架 `a1-0544`/`a1-0545` 两条既有重复种子词（684 → 682），配幂等 `migrateSeedIdAliases()` 把被删 id 下的进度搬到留存 id（两边都有按 reps、reps 相同按 due 取多者），零进度丢失、零孤儿卡。④ 新增动态探针 `tools/wb_merge_probe.mjs`，把真实 `normHw`/`applyMerge`/迁移函数从 `workbench.html` 切片出来在 `node:vm` 里真跑、用真实词库连导两次证明二次导入是 no-op —— **静态正则只能证明「代码长这样」，证明不了「二次导入是 no-op」**；探针对切片有护栏断言（切歪即抛错而非静默假绿），`added`/`merged` 从 `applyMerge` 真实吐出的 toast 解析而非自己算，否则 `merged+added==incoming` 会退化成恒真。本轮六发变异全部致红。测试 **409 全绿**

- [x] **v5.0.0**：**核心词模式切换前置 + 设置即时生效**——工作台顶栏新增紧凑分段控件（`核心` / `全部`），scope 从词库视图的 `<select>` 迁移至 review 视图唯一写入口；搜索框旁路 scope（核心模式下搜非核心词能命中）；`renormalizeQueueTail()` 实现 dailyNew / newOrder 设置即时生效（手动追加的词豁免裁剪）；`buildReviewQueue()` 体首 `manualExtraIds.clear()` 确保豁免集跨重建不残留。测试 **428 全绿**

- [x] **v5.0.1**：**多领域专家缺陷修复与安全加固 (Multi-Expert Audit Hardening)**——① **存储与 FSRS**：补全 `RestoreReq` A1 听力/阅读还原字段（彻底根治还原清空 A1 历史），`review_card_sm2` 动态计算 `elapsed_days` 激活 FSRS 幂律遗忘曲线；② **安全与可靠性**：桌面端所有破坏性 DELETE 接口加 `_require_localhost` 回环鉴权，`security.py` 增加 2MB 流式体积拦截与合法端口限制，修复安卓 Edge TTS stdlib 异常降级链；③ **语言学与句法**：修复过去时动词反查碰撞（`standen` 准确反查 `stehen`，`gingen` 反查 `gehen`），句法拓扑识别介词从句后场边界，`writing_rules.py` 修复 `euer`/`eur` 屈折脱落与 `entlang` 前后置格位；④ **前端加固**：`a1_hoeren` 词汇卡全面改用 `jsAttr()` 杜绝单引号 XSS，`main.js` 显式导出 A1 命名空间并绑定切页停止模考。测试 **452 全绿**

- [x] **v5.0.2**：**审计修复与 XSS 消毒 (Post-Audit Fix)**——① **reader.js XSS sink 全消毒**：14 处 raw interpolation 改用 `Number()` / `safeCefr()` / `esc()` / regex strip / `safeTokens()`，彻底关闭通过 backup/restore 导入 crafted processed_json 后在 localhost origin 触发的 DOM XSS；② **A1 模考统计修复**：`log_study_event` 补充 `a1_hoeren` / `a1_lesen` 分支，模考次数与学习时长正确计入 `daily_summary`；③ **德语动词反查修复**：过去时词干拼后缀前先剥 `-e`（`wusste → wusst + en = wussten`），修复弱变化/混合变化动词复数形式索引遗漏；④ **DeLector.spec 测试改进**：CI 干净 checkout 下显式 `pytest.skip` 替代静默跳过。测试 **453 全绿**

- [x] **v5.1.0**：**局域网随时静默同步 Stage B（WebRTC 自动化）**——① 信令端点补 `X-WB-Key` 鉴权并修 POST 预检放行；② **持久配对凭证 + 一键撤销**（撤销即换新 key，替代每会话短码）；③ WebRTC 信令中继 `/api/wb/rtc/signal`（按配对密钥建邮箱、sender 过滤防重放）；④ 前端 `wbsync.rtc` 建连与 DataChannel **静默同步**（信封与 HTTP PUT 同构）；⑤ 断线自动重连 + HTTP 轮询兜底降级（连续失败停手保可达）。Stage A HTTP 轮询保留为兜底。全量 pytest **487 全绿**；9 wbsync 探针 + 40 定向测试无回归。

- [x] **v5.2.0**：**备考域重布局 + 等级可扩展（ADR-0005 Phase 1）**——① **主导航加「备考 (Prüfung)」顶层域**：A1 写作/听力/阅读/口语/词表五模块从「写作润色」「复习卡片」工具容器迁入独立备考域，工具视图回归纯工具语义（写作=纯 essay、卡片=纯复习）；② **exam catalog 目录化**：`/api/exams/catalog` 代码注册目录单源，等级页签与模块卡片数据驱动，加 A2/B1 = 插一行数据（问卷库不入库，YAGNI）；③ **成绩表泛化**：`exam_trials(level,module,…)` 表 + 幂等迁移 A1 存量（旧 `a1_hoeren_records`/`a1_lesen_records` 保留兼容），备份/还原接线收编；④ **导航单源静态入口 + 备考域骨架**、`tools/ia_dom_mount_probe.mjs` 行为级 DOM 探针（node:vm 真跑，回退必红）。测试 **559 全绿**。

- [x] **v5.1.1**：**审计修复收口 + 性能与稳定性 (M1–M5 + M4)**——① **审计修复（M1–M5）**：旧 6 位短码 LAN 面板停用标注并整体禁用（端点已强制配对密钥，死 UI 明示）；AI 判分/成功提示类残余 `alert` 收敛为 notify（写路径保留 + 双面黑白名单护栏）；wb pull 指数退避、RTC 瞬态不累计、阅读计时器防叠；② **性能（M4）**：查词/判题热路径常量模块级提升、复合词拆解与核心词查表缓存、句切分缩写保护正则提升；③ **稳定性**：PWA 版本更新改温和提示不硬刷窗口、TTS blob URL 统一撤销 + 播放请求令牌防错句覆盖、Reader 陈旧响应守卫、AI 请求输入上限与 TTS voice 白名单；④ **安全补漏**：批注删除纳入本机写闸、X-WB-Key 统一 `secrets.compare_digest` 消除时序侧信道、还原不导入 API 配置防 Key 外泄、Anki 导出 HTML 转义防存储型 XSS；⑤ 测试库隔离与断言护栏补齐。**本版同时回补 v5.0.2 → v5.1.1 的版本面同步**（sw.js 缓存键 / index.html 顶栏 / build.gradle / README / AGENTS）。

- [x] **v5.3.0**：**背词工作台全域 Editorial 重塑 + 精读语法雷达 + A2 词汇全域贯通**——① **共享设计系统 Token 层抽离**（`static/css/tokens.css`）并全量接入背词工作台：统一 Academic Modern Editorial 暖纸墨水调色板、`--serif/--sans/--mono` 字体族与 960px 实体期刊画布，彻底消除硬编码中文字体与 Georgia；考纲词表只读契约 `GET /api/cards/vocab` 上线（CEFR/范围过滤 + 内存解析缓存），工作台顶栏扩展 3 档「⭐ A1 核心 / A1 全量 / 精读生词」范围选择；② **ADR-0006 背词工作台 Zettelkasten 实体学术卡箱与心流优先重塑**：出版物下划线轻量 Tab 导航与聚焦顶栏、剥离厚重阴影与大圆角容器、纯白学术抽认卡纸张层叠翻转（40px 衬线词头）、矿物植物印章式四级柔色评分座（键盘快捷键角标），自测题选项/拼写输入框/KPI 统计/词库浏览表全量 Editorial 化；③ **Grammatik-Radar 精读语法雷达（ADR-0007）**：消除 600ms hover 被动弹出，改行内幽灵微胶囊（Quiet Ghost Pill）显式点击触发句法抽屉（零心流打扰、保护查词抽屉状态）；语料语法 6 维指标（从句复合度/五场域展开率/句框跨度比/关系从句率/虚拟语气率/被动被动态率）落盘 `corpus_syntax_stats` 表 + `POST/GET /api/syntax/stats` 端点，句法抽屉内嵌零外部依赖 SVG 蛛网雷达图对比「本文维度 vs 语料平均基准」；④ **A2 词汇与全域背词系统扩展**：歌德 A2 **974 词全量规范化**（`format_vocab_headword` 精确拼装 497 名词定冠词如 `das Abenteuer` 并首字母大写，动词/形容词保持小写），`GET /api/a2/vocab` + `exam_catalog` 注册 A2 词表模块（动态推导 974 题量，打包 hidden-import 守卫），工作台顶栏第 4 档「📘 A2 词库」异步按需同步持久化，备考域激活 A2 考纲 Tab（3D 扑克翻转/例句发音/网格模式/搜索过滤/加入复习盒）。测试 **582 全绿**（基线 559 → 582）；10/10 Node.js 行为探针全绿（含 13/13 切片护栏 100% 保护）。

- [x] **v5.4.0**：**遇见区 i+1 阅读桥 + Go DAG job#1 内容生产引擎（ADR-0010，PR #25–#27）**——① **遇见区 P0（A1–A7）**：`encounter_texts` 存储 + `/api/encounter` 路由与 `import-pack` 契约（`encounter-pack/v1`，幂等）+ 逐词注解 + `view-encounter` SPA + deck 桥已背词高亮（剥冠词 lemma 判定）+ 生词一键进卡（IndexedDB `wb/words` 双写）+ 会话小复习；② **Go DAG job#1 真执行（B1–B9）**：`delector job run encounter-pack` 本地语料→分级卡包——corpus 两阶段有界扫描（`--max-articles/--max-file-bytes` 护栏）、Pack schema + TokenBudget（含 Release）、DeepSeek gloss（429/5xx 退避）、worker-pool runner（共享预算 + 墙钟 2h 兜底）、cobra CLI 默认护栏，工具注册升至 **6**（新增 `vocab_stats`），`-tags integration` 真链路 `TestEncounterRealChain` PASS；③ **vault-team 评审 8 条修复**：备份/还原纳入 `encounter_texts`、进卡 IDB 双写、403 人话提示等；④ 同期合入 PR #25 备考域独立域迁移（ADR-0005）与 PR #26 自托管字体/弹窗修复。测试基线 **686 passed + 1 skipped**；Go `go test -race ./...` 与 `-tags integration` 全绿。

- [x] **v5.5.0**：**内容供给侧 —— 遇见区开箱即读 + A7 验收自动化**（PR #39，2026-09-10）——① **A7 双端手工冒烟退役**，改由自动化接管：`tests/test_encounter_journey_e2e.py`（6 用例：deck 镜像 / 加短文 / annotate 已知-未知**双向**断言 / 本地词典离线取义（AI tier 打桩抛错）/ 进卡后镜像回读 / 无 key PUT 403）+ `tests/test_encounter_journey_probe.py`（5 用例：**真实 annotate JSON** 驱动逐字节拷贝的 `deck-bridge.mjs`，钉高亮 / 覆盖 / `unknown_top` 排除已背词 / word-only 进卡 / `DECK_KEYS` 常量），真机部分记为发版后一次性点检；② **预置分级短文**：`tools/build_encounter_seed.py` 离线读 `OFFICIAL_CORPUS` → spaCy 分词 + `vocab_stats` 同源分析 → `encounter-pack/v1`，产物 `delector/data/encounter_seed_dict.py`（纯数据第 9 个 data dict，**4 篇 A1×2/A2×2**，零 LLM 零网络，两次生成字节一致）；③ **启动即 seed**：`seed_preset_encounter_texts`（空库守卫 + `pack_id` 幂等 + 逐包异常隔离）由 `create_app()` 在 `seed_preset_articles` 之后调用（**不进 `init_db`**，守住「空库=空列表」6 条既有契约）→ 新装/空库首启即可读，用户已有内容不被动；④ 打包面三处注册同步（data dict 8→9）+ 守卫逐条钉死；⑤ 同期基建：PR CI 门禁 `ci.yml` + dependabot 三生态周更 + `.gitattributes` 锁 `*.go eol=lf`（查明「11 个 gofmt 不洁文件」系 autocrlf 假阳性）。测试基线 **715 passed + 1 skipped**；PR CI（ubuntu，含 node 探针）1m53s 绿。

- [x] **v5.5.1**：**修复 PWA 更新提示不可交互与常驻遮挡**（PR #40，2026-09-13）——① 「新版本已就绪」提示的刷新动作原先绑在 `#wb-notify` 上，而 `.wb-notify` 带 `pointer-events: none`（toast 的非阻断语义，用于不拦截下层点击）→ `onclick` 物理不可达（用户报障「点了没用」）；② 该提示用 `sticky: true` 且无任何关闭入口 → 常驻遮挡界面（「一直站在那里」）。修法：独立的 `#wb-update-bar`（`pointer-events: auto`）+ 两条明确出路「立即刷新」/「稍后」；新增 `tests/test_pwa_update_notice.py` 两条可用性契约（先红后绿），并以真实浏览器 `elementFromPoint` 命中测试验证点击可达（非字符串断言）。测试基线 **717 passed + 1 skipped**。**本版必须覆盖安装才能让 Android 端生效**（static 打包在 APK 内）。

- [x] **v5.5.2**：**Ruff + Mypy 双静态门禁 + WiFi 手机拉取式内容分发**（PR #41/#43/#42，2026-09-13）——① **Ruff 清账**：`select = ["E","F","I"]` + `line-length = 120`（数据字典 E501 豁免），存量 2265 告警 → 零（E501 占 93%），`ruff format` 全量 106 文件，`ci.yml` 接入门禁（不进 requirements，Android 纯净），守卫测试钉死规则集与豁免面；② **Mypy 适度严格档**（`check_untyped_defs`+`no_implicit_optional`+`warn_unused_ignores`+`warn_redundant_casts`+`ignore_missing_imports`，配置落 `pyproject.toml` 的 `[tool.mypy]`——不放 mypy.ini 以免 GBK 解码崩），138→0 错误（VerbTrio 类级注解一次消 20 处、spaCy 降级带理由豁免），**顺带修 2 处真实缺陷**（`start.py` 给已不存在的 `install_signal_handlers` 赋值致 Android 禁信号防护静默失效；`test_audit_regressions.py` 传 3 个不存在字段名），`ci.yml` 接入门禁；③ **遇见区内容分发改为手机拉取式（WiFi）**：因 `start.py` 中 Android 实例有意绑 `127.0.0.1`（避免无鉴权 `POST /api/settings` 暴露局域网）致「桌面推手机」不可达，反转方向——桌面绑 `0.0.0.0` 作只读货架（`GET /api/encounter/packs` 清单 + `/packs/{id}` 完整 v1，绝不提供写操作、不泄露正文），手机 `POST /api/encounter/pull-pack`（localhost 闸 + 5s 超时）拉取 → `validate_pack` → `import_encounter_pack` 幂等落库，前端「📥 从电脑导入」只调本机相对路径（同源零跨域）；Go 侧与 Android 打包面零改动。测试基线 **788 passed + 1 skipped**（含 WiFi 32 + Ruff 5 + A7 22）；本版 static 打包在 APK 内，Android 需覆盖安装生效。

- [x] **v5.6.0**：**听力微训工坊 —— 备考域三模式听练**（PR #44，2026-09-14）——① **L 精听 / 影子跟读**：逐句播放 + 变速/重复/循环 + 跟读停顿；② **D 听写诊断**：隐藏文本逐句听写 → `diagnose_diktat` 词级 LCS 逐字归因（correct/umlaut/case/inflection/missing/extra 六色胶囊）；③ **C 听力填空**：动词/名词启发式挖空 + 填答校验。材料源复用遇见区分级短文（encounter）+ A1 听力音频句库（`a1_hoeren` 的 `audio_text_de`）；后端 `delector/services/listen.py`（`diagnose_diktat` + `make_cloze` 纯函数）+ `delector/routes/listen.py`（`/api/listen` materials/diagnose/trials 四端点）+ `listen_trials` 表（对齐 `exam_trials` 模式，随备份还原）；前端 `static/js/listen-lab.js` 挂进备考域。测试基线 **788 passed + 1 skipped**（基线 751→788，净增 35：引擎 21 + API 9 + 探针 2 + 模块图 3）；Android 真机 TTS 链路留发版后一次性真机点检。

- [x] **v5.7.0**：**长难句精读工坊 —— 备考域句子级攻坚**（PR #45，2026-09-14）——① **句子难度评分引擎**：`delector/services/syntax_score.py` 7 维加权评分 0–100（从句深度/从句复合度/被动/虚拟式/VL 句框/关系从句/句长）+ `estimate_level` CEFR 带估算 + `rank_sentences` 全文切句评分（复用红线 10 唯一切句 `split_sentences_pure_python`，spaCy/纯 Python 双路径带 `path` 降级标注，红线 1）；② **跨语料挑句**：`GET /api/syntax/hard-sentences` 按 source（article/encounter/all）× level × min_score × limit 挑句，进程内存缓存 + limit 护栏；`GET /api/syntax/hard-sentence/<sid>/detail` 句法树+原句+源元信息；③ **拆解→揭示句法树**：句卡先"尝试拆解"（默认隐藏句法树）→ 揭示渲染 clause_tree/topology + 查词链路（`/api/lookup/vocab`）；④ **入复习盒 + 成绩落盘**：「加入复习盒」复用 `saveGrammar` 语义写 `grammar_cards`（不新建卡种表，同句已入盒显示"已加入"）；会话成绩 `POST /api/syntax/hard-sentence/<sid>/trials` 落 `hard_sentence_trials` 表（对齐 `listen_trials`，随备份还原）；⑤ **等级门控适配过渡期**：默认 A2+ 门控（可切全部），`path="pure"` 句显示"近似分析"提示，评分仅参考。测试基线 **828 passed + 1 skipped**（基线 788→828，净增 40：引擎 16 + API 11 + 探针 5 + 模块图 8）；Android 端 static 打包在 APK 内，需覆盖安装生效。

- [x] **v5.7.1**：**长难句工坊 Android 真机 500 热修**（2026-09-14）——v5.7.0 真机点检报「长难句清单加载失败 Internal Server Error」：Android 环境（spaCy/数据差异）某句 `analyze_syntax_tree` 抛异常，而 detail 端点是唯一无容错路径（`rank_sentences` 有逐句 try/except 跳过坏句，detail 没有）→ 点击揭示句法树 500；`source=all` 全语料榜整榜遍历任一材料异常 → 空态。修法：① detail 单句分析失败降级 **404「该句暂无法分析」**（不 500，对齐 rank_sentences 容错纪律）；② `_rank_source` 切句异常 → 单材料空榜；③ `source=all` **逐材料隔离**（坏材料 SQL/切句异常只丢自身，不炸整榜）。回归测试 +3（detail 分析抛→404 人话 / 切句崩→空榜 200 / all 坏材料→其余材料仍上榜）。测试基线 **831 passed + 1 skipped**（828→831）；Android 需覆盖安装生效。

- [x] **v5.7.2**：**长难句工坊 500 真根因修复 —— Android pydantic 1.x 兼容**（2026-09-14，vault-debug 4 步）——v5.7.1 复测仍报「长难句清单加载失败 Internal Server Error」：Android Chaquopy 打包 `pydantic<2.0.0`（1.10.x）+ `fastapi<0.100.0` + Python 3.10（build.gradle:84-92），而 `syntax_score.rank_sentences` 用了 **`model_copy()`（pydantic v2 专属 API，1.x 不存在）** → AttributeError → `/api/syntax/hard-sentences` 全源 500（桌面 pydantic 2.x 无法复现，上轮 detail 容错/all 隔离未触碰此行故无效）。修法：`model_copy` 改为直接构造 `SentenceScore`（v1/v2 通用，对齐 `routes/main.py` 既有 `hasattr` 兼容纪律）；全仓排查确认仅此 1 处 v2 专属 API；新增**跨端打包兼容守卫** `test_syntax_score_no_pydantic_v2_only_api`（regex 钉死 syntax_score.py 无 `.model_x(` 调用，落实 DELECTOR-DEV-RULES §2.4）。验证：临时 venv（pydantic 1.10.26 + fastapi 0.99.1）复现 `model_copy` 缺失 + 修复后 `rank_sentences` 正常出句；测试基线 **832 passed + 1 skipped**（831→832）。Android 需覆盖安装生效。

- [x] **v5.7.3**：**揭示句法树 `[object Object]` 渲染修复 + 难度分文案消歧**（2026-09-14，vault-debug）——v5.7.2 复测报：揭示句法树只能看到 `[object Object],[object Object]`（用户简记 [object, object]）。根因：`_topologyHtml` 的 `Array.isArray(ft) ? ft.join(" ") : topo[key]` —— `field_texts` 在 spaCy 与纯 Python 双路径恒为**字符串**，恒走 else → `vals = topo[key]`（原始 token 数组）→ `String(数组)` 渲染成 `[object Object]`；**探针 fixture 误用数组 field_texts（与真实 API 形状不符）→ 恒走 join 分支 → 漏检**。修法：`_topologyHtml` 优先取 `field_texts` 字符串原文，缺失才退化顶层 token 数组 join；探针 fixture 改真实形状 + 新增 2 断言（无 `[object Object]` / 渲染字符串原文），46 断言 + 3 变异全绿。附带消歧：「当前 x/100」实为**难度分**（非句次序，进度在卡面"句 x/y"；列表按难度降序 → 点上一句分数变大属正常），文案改「当前句难度 x/100」。测试基线 **832 passed + 1 skipped**；Android 需覆盖安装生效。

- [x] **v5.7.4**：**pure 降级评分增强 + 前端字号 + spaCy 诊断**（2026-09-14）——① **pure 路径评分增强**：v5.7.3 真机反馈纯 Python 降级句"普遍 5/100 无区分度"（pure 树单节点无 features，只剩句长维度）。`syntax_score` 新增 `_pure_text_hints` 文本启发式（逗号/从属连词 → clause_count 粗估；`wird/wurde` → 被动；`würde/hätte` → 虚拟式；`, weil/dass` → VL 句框；`, der/die` → 关系从句），`score_sentence` 在 `path="pure"` 时注入，难度榜恢复排序依据（**评分仍是内部启发式非权威，排序供参考**）；② **前端字号优化**（字小又累）：材料卡片 13→15px、原句 17→18px、揭示树/拓扑 13→15px+行高 1.85、树节点类型 11→12px、卡片留白加大；③ **文案软化**：`⚠ 近似分析（纯 Python 降级路径，评分仅供参考）` → `✦ 轻量分析：难度画像为粗估，排序供参考，不必当真`；④ **spaCy 加载诊断**（免 adb）：`GET /api/syntax/spacy-status` 返回 `{path, error}`（spaCy import/模型加载失败的具体异常），前端「轻量分析」提示旁自动展示——用于定位 Android 打包 spacy+de_core_news_sm 却仍走 pure 的根因。测试基线 **838 passed + 1 skipped**（832→838：pure 启发式 +5、spacy-status +1）；Android 需覆盖安装生效。

- [x] **v5.7.5**：**spaCy 诊断竞态修复**（2026-09-14）——v5.7.4 复测：长难句工坊显示「轻量分析」但诊断小字不出现。根因：`enterHardSentences` 里 `_loadSpacyDiag()` **未 await**，`_renderAll()` 在诊断请求返回前抢先渲染，`_q.spacyError` 仍是空串 → 诊断永不渲染。修法：await 诊断就绪后再渲染 + `path="pure"` 且 error 空时显示占位「未捕获到加载异常（需进一步排查）」。探针 46 断言全绿；测试基线 **838 passed + 1 skipped**；Android 需覆盖安装生效。

- [x] **v5.7.6**：**spaCy 诊断 error 永远为空修复**（2026-09-15）——v5.7.5 真机：`/api/syntax/spacy-status` 返回 `path:"pure"` 但 `error:""`，前端兜底显示「未捕获到加载异常（需进一步排查）」。根因：**Python from-import 按值拷贝不可变对象**——`syntax_hard.py` 用 `from syntax_tree import _spacy_load_error` 拿到的是导入时的初始空串；`get_spacy_nlp()` 内 `global` 重绑定只改 `syntax_tree` 模块命名空间，route 持有的旧引用不变 → error 永远空（**spaCy 实际并未加载成功**，`path:"pure"` 即铁证）。修法：`syntax_tree` 新增 `get_spacy_load_error()` getter，route 改调函数实时读取；回归测试 `test_spacy_status_reports_live_error_on_pure_path` 锁定（mock get_spacy_nlp→None + 设实时错误，断言 endpoint error 等于实时值）。测试基线 **839 passed + 1 skipped**（838→839）；Android 需覆盖安装 v5.7.6 后诊断小字才显示真实 spaCy 加载异常，用于定位 Android 走 pure 的根因。

- [x] **v5.7.7**：**真机 spaCy E050 根因修复 —— dist-info 缺失**（2026-09-15，vault-debug）——v5.7.6 诊断小字首次显示真实错误：`E050 Can't find model (md 与 sm 双模型)`。根因排查：APK 解包显示模型文件 44 项全完整、`extract_packages` 生效、spaCy import 正常——但 spaCy 3.8 的 `is_package()` 实现是 `importlib.metadata.distribution(name)`，**只认 pip 元数据（.dist-info）不碰文件系统**；CI 把 `de_core_news_sm` 包目录 `cp -r` 进 APK 时**漏拷了平级的 `de_core_news_sm-3.8.0.dist-info`** → 真机判定"不是 Python 包" → E050。用独立 venv 干净复现：仅包目录 `is_package=False + E050`；补上 dist-info 后 `is_package=True + spacy.load OK`。修法：① CI "Sync Python Backend" 步骤用 glob 定位 dist-info 并连拷进 `src/main/python`；② CI APK 探针加 `dist-info-complete` 精确守卫（v5.7.6 旧 APK 被正确拦截、新 APK 放行，本地用真实 APK 验证）。测试基线不变（纯 CI 打包层修复）；Android 需覆盖安装 v5.7.7、长难句工坊从「轻量分析」切回 spaCy 完整解析。

- [x] **v5.8.0**：**ADR-0011 词库单一真相化 + 等级判定数据驱动正式发布**（2026-09-15，PR #46）——① 背词工作台词库改为**单一数据真相**（`delector/data/a1_workbench_dict.py` 682 词 / 213 核心 / 22 自定义，A1 704 / A2 974 / B1 1712 同契约），根除 HTML 正则解析与静默回退（服务端直接 import 数据模块，缺失抛 RuntimeError）；② 四路径契约统一（9 字段集 `{id,hw,pos,gender,plural,de,zh,core,cefr}`）；③ 前端 `normalizeWord` 幂等归一 + `wb.schema.v1` 一次性迁移（id/进度零丢失，merge 探针全绿）；④ scope 判定数据驱动（`SCOPE_PREDICATES` + `isInScope`/`cefrOf` 唯一入口，13/13 切片护栏零漂移）；⑤ **新增 B1 入口**（工作台第 5 档 + 备考域 B1 页签 + 徽标动态化，catalog `count_fn` 动态推导零硬编码）+ `/api/cards` 信封解包修复。测试基线 **883 passed + 1 skipped**（838→883 净增 44）；Android 需覆盖安装 v5.8.0 生效（B1 入口 + normalizeWord 迁移）。

- [x] **v5.9.0**：**词库富字段与主干分层正式发布**（2026-09-16，PR #54/#55/#56/#57）——① **ADR-0012 词汇主干落地**：`delector/core/lexicon.py`（分片注册表 + provenance + 字段级优先级「cefr 官方 > 手编 > AI、富字段 手编 > 官方 > AI」；`CORE_VOCAB_DB == LEXICON == 4762` 单真值）+ 官方歌德 A1/A2/B1 词表迁入 `delector/data/official_vocab.py`（备考域/工作台 A2 **736**、B1 **1617** 官方精选；`/api/a2/vocab` 默认官方）；② **ADR-0013 输出契约 9→11 字段**（新增 `ipa` / `example_zh`，`de` 语义统一为德语例句）+ 富字段分片 `delector/data/official_vocab_rich.py`（A1 660 / A2 736 / B1 1617，join 零差），**A2/B1 卡片首次具备音标 + 双语例句**；③ **IPA 表示法全局统一**（去 tie-bar，全仓词表 0 残留：A1 seed/custom 10 条归一 + rich 空 IPA 10 条从 A1 seed 回填）；④ **A1 卡片补齐名词 gender/plural**（336/344 = **97.67%**，此前 0%；源 = 主干 LEXICON，与 A2/B1 同源）；⑤ 新增词表来源对账工具 `tools/audit_official_vocab.py` + 归档生成脚本 `tools/gen_rich.py`。测试基线 **972 passed + 1 skipped**（883→972 净增 89）；**Android 需覆盖安装 v5.9.0 生效**（改动含 `static/`）。

- [x] **v5.9.1**：**词库等级标签补齐 + 入口文档瘦身**（2026-09-16，PR #59/#60）——① **工作台词库补 A1 等级标签 `a1`**：此前 A1 只有 `core`（核心语义）而缺等级语义，导致词库工具栏「全部标签」下拉**筛不出 A1**（A2/B1 恰好有 `a2`/`b1`，且词库浏览只在 `core` 档按 scope 过滤，其余档显示全库 → 按标签筛等级是唯一手段）；标签语义统一为 **`a1`/`a2`/`b1` = 等级、`core` = 核心词、`reader` = 精读生词**，种子建表 / `CORE_CUSTOM_WORDS` / 存量 `backfillCoreWords()` 幂等迁移（**不动 FSRS 进度**）。② **修 `reader` 谓词的 `w.custom` 兜底**：22 条 `core-*` 补缺词（`der Wohnort`/`die Nationalität`…）此前被误判为「精读生词」而**同时出现在两档**；收窄为 `tags.includes("reader") || id.startsWith("card-")`。③ **README 瘦身 433 → 131 行（DOC-GOVERNANCE 合规）**：版本历史迁出为 **`CHANGELOG.md`**（70 条历史零丢失，成为版本历史正主）；核心特性 12 子节 → 摘要 + 指针 `FEATURES.md`；目录结构 → 顶层树 + 指针 `docs/agents/architecture.md`；快速启动精简 → 指针 `docs/agents/ops.md`；新增「文档导航」路由表。④ 顺带修正既有滞后：`linguistics`/`syntax_tree` 路径补 `nlp_engine/` 前缀、测试模块数 27 → 60+。测试基线 **973 passed + 1 skipped**；**Android 需覆盖安装 v5.9.1 生效**（改动含 `static/`）。

- [x] **v5.9.2**：**A1 取数统一（ADR-0014）+ 词表富字段回填修复**（2026-09-17，PR #61 + `e2d5504`）——① **A1 取数统一（ADR-0014 S1–S3）**：A1 首装改走 `GET /api/cards/vocab?cefr=A1&scope=all`（API 优先 + 内联降级为 `file://` 离线 fallback + localStorage 缓存 + 失败可恢复重试 + 挂起期占位），输出契约 11→12 字段（+`letter`，服务端下发 seed 原值、不派生——实测 `letterOf` 会在 10 条上漂移 `O↔Ö`/`U↔Ü`）；三条守卫钉死「内联绝不当主路径」。② **A2/B1 富字段回填**：`sync{A2,B1}CardsFromServer` 由 **append-only 升级为「只增 + 只补空字段」**（幂等、绝不覆盖非空、不碰 `cards/log/wrong`）——根治「A2/B1 只有部分词有例句」（根因＝存量词条在首次同步后永久冻结，`ex:[]` 再不刷新；进 A2/B1 档即自愈）；备考域卡片空例句块改**条件渲染**（空值不输出孤立标签）。③ **A1 早退闸修复**：`bootstrapA1Words` 早退闸不再依赖来源标记（旧 `lastSrc !== "inline"` → 改 `!canUseServer`），已以 `server` 落盘的设备**每次启动重新合并** A1 富字段——修「`anbieten`/`allein` 等存量 A1 条目无例句无音标」（旧版构建首装时服务端/种子尚无富字段，裸条目被永久冻结；实测用户 `localStorage` 中 `a1-0011`/`a1-0016` `exLen=0`、`ipa=''`，而 A2 同源条目齐全）。行为级探针新增 A1 早退闸场景 B2 + A2/B1 回填 19 场景（真实源码切片 + `node:vm` 真跑，接入 pytest/CI）。测试基线 **987 passed + 1 skipped**（759 + `test_server` 228；2 条既有 Windows 环境失败 `no such table: exam_trials`，工作区 A/B 证实为既有）；13+ `tools/*.mjs` 探针零漂移；ruff 全绿。**Android 需覆盖安装 v5.9.2 生效**（改动含 `static/`）。

- [x] **v5.9.3**：**类型门禁全仓 `--strict` 清账 + CI 门禁升级 + 工具链修复**（2026-09-18，纯工程治理、**无用户可见变更**）——① **mypy `--strict` 全仓 250→0 清账**（三阶段：`routes/main.py`(62) + `core/database.py`(24) 补注解 → 全仓 133 → `tools/` 108→0），CI 门禁升级为**双轨 strict**（`delector`+`tools` 走 strict、`tests` skip）+ 修正门禁路径拼写（`deletor`→`delector`）；设计见 `docs/specs/2026-09-18-mypy-strict-annotation-sweep-design.md`。② **工具链修复**：`tools/vault-proactive-scan.py` 两缺陷修复、`tools/check_security` 排除 `node_modules`（消除 WASM base64 误报）。测试基线 **987 passed + 1 skipped**（与 v5.9.2 持平；2 条既有 Windows 环境失败 `no such table: exam_trials`）。**本次无 `static/` 改动** → 桌面端即时生效；Android 覆盖安装为可选（无前端变更）。

- [x] **v5.9.4**：**精读生词（reader 档）富字段回填 + 原句优先**（2026-09-20，`a7801ec`）——补最后一个同型缺口：**reader 生词卡此前永远裸**（服务端 `scope=reader` 显式置空富字段 + 前端 `syncReaderCardsFromServer` append-only → 存量永不刷新），与 A1/A2/B1 三档信息量不对齐。① **服务端**：新增 `_reader_lemma_key`（去冠词 + 小写归一——`RICH`/`LEXICON` 键 100% 小写，而写入侧 `lemma` 可能大写/带冠词）+ `_reader_rich_fields`（`rich_of` 取 `ipa`/例句、`a1_lemma_meta_of` 取 `gender`/`plural`——源 = 主干 LEXICON 4762 全量、覆盖非 A1、`lookup_irregular_verb` 屈折形兜底 `ging→gehen`），reader 分支改「**命中才补，未命中留空不编造**」；`de` 语义 = **原句优先**（有 `sentence_context` 保留生词原句且不补 `example_zh`，避免「德文原句 + 官方例句中文」文不对题）。② **前端**：`syncReaderCardsFromServer` 由 append-only 升级为「**只增 + 只补空**」（`ipa`/`ex`/`gender`/`plural`），不覆盖非空、不碰 `cards`/`log`/`wrong`、幂等 → 进「生词」档即自愈。③ 行为级探针 `tools/wb_reader_rich_backfill_probe.mjs`（13 场景，真实源码切片 + `node:vm` 真跑，含防死测守卫）接入 pytest。测试基线 **993 passed + 1 skipped**（765 + `test_server` 228；2 条既有 Windows 环境失败 `no such table: exam_trials`）；15 个 `tools/*.mjs` 探针零漂移；ruff 全绿 / mypy `--strict` 0 error。**Android 需覆盖安装 v5.9.4 生效**（改动含 `static/`）。

- [x] **`server.py`** **拆分重构**（v4.6.4）：3053 行单文件拆为 `nlp.py`（NLP/CEFR/文本分析）、`database.py`（DB/CRUD/备份）、`security.py`（SSRF/URL 安全），`server.py` 保留路由骨架。依赖图无环，319 测试全绿。

- [x] **介词矩阵「已入卡」持久化**（v4.6.4）：新增 `prep_saved` 表 + `GET/POST /api/prep/saved`，前端 `_prepSavedKeys` 从服务端初始化，重进矩阵段按钮状态保持。

- [x] **局域网同步 6 位短码**（v4.6.5）：WebRTC P2P 同步的 SDP 传递从复制粘贴 2-3KB 改为 6 位短码中转（`POST /api/wb/sync/store` + `GET /api/wb/sync/fetch/{code}`），手机上只需输入 6 个字符。

- [x] **歌德 A1 备考工坊**（v4.7.0）：官方考纲 702 词 + 15 大交际主题 + 8 篇官方填表真题与评分容错 + 10 篇 30 词短电邮写作工坊与 3 大导向点合规诊断 + 口语 Teil 2/3 考场题卡。

- [x] **Phase 2b（2026-09）：Go Agent Runtime 绿色便携包**——`delector run` 起 Python NLP 服务（supervisor 退避重启 + 健康探针 + Unix SIGTERM 优雅关闭 / Windows Kill）；自研 goroutine/channel DAG 调度 article-analysis 预设（4 层口径 ingest→[analyze,tts]→writing_check→export）；5 工具注册（golden 防漂移）；go-openai DeepSeek 客户端。**分发形态**：Go 单二进制 × Python venv 跨平台便携包（`agent/scripts/package_agent.py`，产物 `delector-agent/{delector,python,delector-src}`，压缩 ~65MB），三平台 CI `build-agent.yml` 自动出 artifact（**预览通道**，不打 tag 不发布；替换桌面版决策留 Phase 3）。Go 1.26.5；`go test -race ./...` 与 `go test -tags integration` 真实 uvicorn→spaCy 全链路为门禁。

- [x] **遇见区 P0 · Sub-Plan A（2026-09-07，分支 `feature/encounter-job1`，A1–A7 `d5c1155..2d78c09`）**：手选分级短篇 → 阅读视图按本机 deck 把**已背词高亮** + 覆盖统计 → 生词点选本地词典释义 → 一键进卡（写回 deck + wb 同步）→ 读完会话小复习。落地：`encounter_texts` 库 + `/api/encounter{list,detail,add,annotate,import-pack}`（`encounter-pack/v1` 契约，import 幂等）+ `view-encounter` SPA（`encounter.js`/`deck-bridge.js`）。测试基线 **673 全绿 + 1 skipped**。master 门禁（含 Go DAG job#1 import-pack 真链路）留 Sub-Plan B。

- [x] **Go DAG job#1 真执行 · Sub-Plan B（2026-09-07，分支 `feature/encounter-job1`，B1–B8 `a1e4245..13d8535`）**：agent 从「只装配」变**首个真执行 job**——`delector job run encounter-pack` 扫本地语料 → 去重/限量/并发逐篇 DAG（analyze→vocab_stats→DeepSeek gloss→export_pack）→ 可选投递 `POST /api/encounter/import-pack`。落地：`internal/corpus` / `internal/job`（Pack schema、TokenBudget、gloss、DAG、runner）/ cobra 接线 / `-tags integration` 真链路门禁（`TestEncounterRealChain` PASS）。Go registry + Python 工具清单升至 **6 工具**（新增 `vocab_stats`）。Python 全量 **686 passed + 1 skipped** 零回退；`go test -race ./...` 与 `-tags integration` 全绿；CLI dry-run + 真实 run（stub LLM）冒烟退出 0。真实 DeepSeek 冒烟档 PENDING-作者（桌面无 key）。
