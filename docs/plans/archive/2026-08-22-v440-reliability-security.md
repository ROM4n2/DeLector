# v4.4 可靠性与安全收口实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不增加大型新功能的前提下，消除局域网配置风险，补齐提交与 Android 发布闸门，降低写作诊断误报，并完成关键回归测试。

**Architecture:** 保持现有 FastAPI、原生 ES Modules、SQLite、Chaquopy 架构。安全限制放在共享 API 边界；发布检查放在现有 pre-commit 与 GitHub Actions；写作规则只在新增反例证明问题后做最小修正。

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, spaCy, pytest, SQLite, Gradle, Chaquopy, GitHub Actions, POSIX shell.

**Spec:** 本计划即 v4.4 范围定义；不依赖独立设计文档。

## Global Constraints

- 不新增运行时依赖。
- Android 版本互锁保持不变：Python 3.10、minSdk 24、spaCy 3.8.7、`arm64-v8a`。
- Android 仍只监听 `127.0.0.1`。
- 桌面端保持局域网阅读能力，但局域网请求不得修改敏感设置。
- `app.mount("/", StaticFiles(...))` 必须继续位于 `server.py` 最末尾。
- 真实 API Key、keystore、数据库和 APK 不得进入 Git。
- 每个非平凡修改都必须有最小可运行回归检查。
- 不修改与 v4.4 目标无关的既有功能。

---

### Task 1: 建立安全边界测试

**Files:**
- Modify: `test_server.py`（设置接口与绑定行为测试区域）
- Create: `test_start.py`

**Interfaces:**
- Consumes: `server.app`, `start.get_bind_host`, `start.is_android`
- Produces: 可验证的本机来源判定契约，供 Task 2 实现

- [ ] **Step 1: 写设置接口失败测试**

增加测试，构造非回环客户端请求，断言 `POST /api/settings` 与 `POST /api/settings/test-key` 返回 `403`，且数据库中的敏感设置未改变。

- [ ] **Step 2: 写回环请求测试**

断言测试客户端以回环来源访问时，合法设置更新仍返回成功；已有 `/api/settings` 行为保持不变。

- [ ] **Step 3: 写平台绑定测试**

通过 monkeypatch 模拟 Android 环境与桌面环境，断言 `get_bind_host()` 分别返回 `127.0.0.1` 与 `0.0.0.0`。

- [ ] **Step 4: 运行失败测试**

Run: `pytest test_server.py test_start.py -q`

Expected: 新增来源限制测试失败；既有测试不应因测试文件缺失以外的原因失败。

- [ ] **Step 5: Commit**

```bash
git add test_server.py test_start.py
git commit -m "test: define v4.4 settings security boundary"
```

### Task 2: 限制敏感设置接口来源

**Files:**
- Modify: `server.py:1782-1837`
- Modify: `start.py:27-37`（仅在需要抽取可测试判断时）
- Test: `test_server.py`, `test_start.py`

**Interfaces:**
- Consumes: Task 1 的来源测试
- Produces: `GET /api/settings` 保持可读；敏感设置写入与 API Key 测试接口仅接受本机来源

- [ ] **Step 1: 增加共享来源检查**

在设置写入与测试接口共用的边界位置检查 `Request.client.host`。接受 `127.0.0.1`、`::1` 和等价 IPv4-mapped loopback；无法确认来源时拒绝，不默认放行。

- [ ] **Step 2: 保持 Android 行为**

确认 WebView 通过 `127.0.0.1` 访问仍成功；不改变 `get_bind_host()` 的 Android 分支。

- [ ] **Step 3: 运行安全回归**

Run: `pytest test_server.py test_start.py -q`

Expected: 所有设置与绑定测试 PASS。

- [ ] **Step 4: 运行全套测试**

Run: `pytest -q`

Expected: 全部测试 PASS。

- [ ] **Step 5: Commit**

```bash
git add server.py start.py test_server.py test_start.py
git commit -m "fix(security): restrict sensitive settings to localhost"
```

### Task 3: 修补提交密钥扫描缺口

**Files:**
- Modify: `.githooks/pre-commit`
- Modify: `test_server.py`（若现有静态守卫测试集中于此）
- Test: `.githooks/pre-commit` 的 shell 级行为

**Interfaces:**
- Consumes: 当前暂存文件扫描、文件名白名单与 `delector:allow-secret` 约定
- Produces: 对 PKCS12 Base64 文件的最小检测，不误报公开证书与示例文件

- [ ] **Step 1: 写扫描样例测试或可重复 shell 检查**

覆盖以下输入：带敏感文件名的 `.p12`/`.pfx`、包含 PKCS12 Base64 内容的普通文本文件、`.example`/`.sample` 文件、公开 PEM 证书。

- [ ] **Step 2: 运行检查确认缺口**

Run: `bash .githooks/pre-commit`（使用临时 Git index 或现有钩子测试方式）

Expected: PKCS12 Base64 样例当前未被完整覆盖。

- [ ] **Step 3: 增加最小规则**

复用现有文件名与内容扫描逻辑；只识别足够明确的 PKCS12 Base64 特征，保留 `.example`、`.sample`、`.template` 例外与行内豁免规则。不要用通用 `MII` 前缀单独判定所有文本。

- [ ] **Step 4: 运行扫描回归**

Run: `git diff --check`

Expected: 无空白错误；敏感样例拒绝，合法样例放行。

- [ ] **Step 5: Commit**

```bash
git add .githooks/pre-commit test_server.py
git commit -m "fix(security): cover encoded keystore files"
```

### Task 4: 加固 Android CI 构建验证

**Files:**
- Modify: `.github/workflows/build-release.yml`
- Modify: `test_server.py`（现有 Android 工作流静态契约测试）
- Inspect only: `android/build.gradle`, `android/app/build.gradle`

**Interfaces:**
- Consumes: 现有 Gradle 构建、keystore 指纹、`extractPackages`、APK 内容检查
- Produces: CI 中可重复的 Android 编译与打包验证

- [ ] **Step 1: 写 CI 静态契约测试**

断言工作流保留 JDK 17、Android 构建命令、`keytool -printcert -jarfile`、期望指纹检查，并声明模型与三个 `extractPackages` 包。

- [ ] **Step 2: 运行静态测试确认缺口**

Run: `pytest test_server.py -k "android or workflow or signature or extractPackages" -q`

Expected: 缺失的 CI 构建契约测试先失败，已有契约保持通过。

- [ ] **Step 3: 补最小 CI 构建步骤**

在现有 Android 资产生成之后执行 Gradle assemble 任务；复用已有 JDK、缓存、签名和产物检查，不新增平行构建流程。

- [ ] **Step 4: 增加 APK 内容断言**

检查 `assets/chaquopy/app.imy` 或对应 APK 内部产物包含 `server.py`、`de_core_news_sm`、`spacy` 与 `thinc`；不要直接以 APK 根目录查找 Python 文件。

- [ ] **Step 5: 运行本地静态验证**

Run: `pytest test_server.py -k "android or workflow or signature or extractPackages" -q`

Expected: PASS。完整 Gradle 构建由 CI 验证；本机无 Android SDK 时不得伪称本地构建通过。

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/build-release.yml test_server.py
git commit -m "ci(android): verify build and packaged NLP assets"
```

### Task 5: 补写作规则反例并修最小误报

**Files:**
- Modify: `test_writing_rules.py`
- Modify: `writing_rules.py`（仅测试证明需要时）

**Interfaces:**
- Consumes: `analyze_essay_text`, `detect_determiner_noun_agreement`, `detect_preposition_case`
- Produces: 兼容现有分析 JSON 的更可靠错误与提醒结果

- [ ] **Step 1: 增加反例测试**

覆盖零冠词名词、固定介词搭配、双向介词、缺失词典性别、spaCy 缺席降级，以及合法冠词/格位组合。

- [ ] **Step 2: 运行反例测试**

Run: `pytest test_writing_rules.py -q`

Expected: 真实可复现的误报测试失败；若全部通过，不修改规则代码。

- [ ] **Step 3: 修改共享规则路径**

只在共享检测函数中修正根因。保持无足够格、性、词性信息时跳过；不得通过放宽守卫换取更高召回率。

- [ ] **Step 4: 运行写作与服务端回归**

Run: `pytest test_writing_rules.py test_server.py -q`

Expected: PASS，分析 JSON 字段与版本兼容。

- [ ] **Step 5: Commit**

```bash
git add writing_rules.py test_writing_rules.py
git commit -m "fix(writer): reduce proven grammar false positives"
```

### Task 6: Android、备份与 AI 错误回归

**Files:**
- Modify: `test_server.py`
- Modify: `static/js/*.js`（仅定位到现有错误显示路径时）
- Inspect: `server.py` 备份与 AI 路由

**Interfaces:**
- Consumes: 现有备份 token、回滚逻辑、AI HTTP 错误处理、Android 回环访问
- Produces: 关键失败场景的自动化保护

- [ ] **Step 1: 增加备份来源测试**

断言非本机请求不能调用备份准备、下载与恢复；回环请求仍可执行；恢复失败后原始数据库内容保持不变。

- [ ] **Step 2: 增加 Android spaCy 加载契约测试**

静态检查 `module.load()` 回退、`extractPackages`、模型目录与 `is_android()` 网络下载门控。

- [ ] **Step 3: 增加 AI 402/网络失败测试**

模拟 HTTP 402、超时和非 JSON 错误，断言 API 返回明确错误状态，前端不显示成功结果、不吞异常。

- [ ] **Step 4: 只修必要错误显示**

复用现有 `api()` 与错误提示路径；不新增通知框架，不把 API Key 或响应正文中的敏感内容写入 DOM/localStorage。

- [ ] **Step 5: 运行回归**

Run: `pytest -q`

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add test_server.py static/js
git commit -m "test: cover backup and AI failure paths"
```

### Task 7: 补词库缺口并更新发布文档

**Files:**
- Modify: `core_dict_ext.py` 或词库生成输出文件（仅使用现有生成流程）
- Modify: `README.md`
- Modify: `FEATURES.md`
- Modify: `AGENTS.md`
- Modify: `static/index.html`, `static/sw.js`（仅当 JS/CSS 发生改动）

**Interfaces:**
- Consumes: 现有 `tools/build_dict.py`、原始 AI 响应缓存与词库校验流程
- Produces: v4.4 发布记录、已知问题同步、词库缺口减少

- [ ] **Step 1: 盘点缺口**

运行现有词库检查，记录约 109 个缺口的实际集合；不按连字符统一过滤。

- [ ] **Step 2: 补跑现有生成流程**

使用 `python tools/build_dict.py --refill --parallel 8`，保留原始响应缓存；校验在读取阶段执行。

- [ ] **Step 3: 抽查非 seed 路径**

抽查失败重试词、派生词、连字符词和形容词屈折形，避免只抽查人工 seed。

- [ ] **Step 4: 更新文档**

记录 v4.4 完成项、未完成项、测试数量和 CI 限制；不删除仍存在的 Android、DeepSeek、md 模型风险。

- [ ] **Step 5: 运行最终验证**

Run: `pytest -q`

Run: `python -m pyflakes server.py syntax_tree.py start.py`

Run: `git diff --check`

Expected: 测试全绿；仅保留既有、明确记录的 pyflakes 重复键告警；无 diff 格式错误。

- [ ] **Step 6: Commit**

```bash
git add core_dict_ext.py README.md FEATURES.md AGENTS.md static/index.html static/sw.js
git commit -m "docs: prepare v4.4 reliability release"
```

## Release Acceptance

- `pytest` 全绿。
- `python -m pyflakes server.py syntax_tree.py start.py` 无新增告警。
- 局域网不能修改敏感设置。
- pre-commit 能拦截明确的编码 keystore 文件，且示例文件、公开证书不误报。
- GitHub Actions 完成 Android Gradle 构建、APK 内容检查和签名检查。
- Android spaCy 使用真实模型加载路径，不静默退回 pure Python。
- 写作规则新增反例全绿，未降低已有误报防护。
- 不提交 `.env`、`*.db`、keystore、APK 或真实 API Key。

## Explicitly Deferred

- 新学习模式、社交功能、账号系统。
- Android 离线 TTS 引擎。
- `de_core_news_md` 本机安装；由 CI 覆盖可选加载路径。
- 大规模写作规则重构。
