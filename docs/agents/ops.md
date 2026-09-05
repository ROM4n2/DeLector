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
测试:      pytest            （582 个，全绿）
行为探针:  node tools/<name>.mjs（10 个，发布闸要求 10/10 全绿，含 wb_queue_probe 13/13 切片护栏）
打包:      python package_windows.py（Windows 便携版）；Android: cd android && ./gradlew assembleDebug
静态检查:  python -m pyflakes server.py syntax_tree.py start.py linguistics.py
```

**Git 推送通道**：这台机器上 HTTPS 连 fetch 都会失败（`schannel: failed to receive handshake`），
`origin` 已指向 `ssh://git@ssh.github.com:443/ROM4n2/DeLector.git`（22 端口时通时不通，443 稳定）。
`gh` CLI 走自己的 HTTPS API 认证，不受影响。

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
8. **每次 git 推送必须同步更新 README.md（MUST）**：发版/修复涉及版本号、特性、测试数、
   目录结构、路线图任一变化时，README 的对应落点要同一提交内更新到位（Release badge、
   下载表版本与 release 链接、Tests badge、核心特性节、技术栈测试数、目录结构 js 模块与
   测试文件清单、Roadmap 版本条目）。不要等发布后再补——README 是仓库门面，滞后会让
   用户/协作者看到与代码不一致的版本。
9. **大改动后**：更新 `WORKMEMORY/PROJECT_OVERVIEW.md` 的「当前状态」「红线速查」「开放待办」；
   发布类变更同步 README Roadmap changelog。
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

---
