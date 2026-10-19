# 安全策略 (Security Policy)

DeLector 项目高度重视系统的安全性、个人数据隐私与离线优先的防御性设计。

---

## 🛡️ 支持的版本 (Supported Versions)

我们仅针对最新发布的版本提供安全补丁与漏洞修复支持：

| 版本 | 是否支持安全更新 |
| :--- | :--- |
| **v5.18.x** | :white_check_mark: 支持中 |
| < v5.18.0 | :x: 不再维护（请升级至最新版本） |

---

## 🔒 安全设计不变量 (Security Invariants)

1. **本地优先与数据自持**：
   - 用户的所有背词进度、阅读笔记、错词记录与文库均仅保存在本机（桌面端为 `%LOCALAPPDATA%\DeLector` 或指定的数据目录；Android 端为沙盒私有存储）。
   - 严禁将未经用户显式操作的数据同步至未授权的第三方云端。
2. **敏感端点与写入回环保护 (`_require_localhost`)**：
   - 包含设置修改、文库删除、备份还原等具有破坏性/修改性质的 REST API 端点，必须经过 `_require_localhost` 依赖拦截，仅允许来自本地回环地址（`127.0.0.1` / `::1`）的访问，防止局域网恶意攻击。
3. **零 XSS 注入**：
   - 前端所有模板变量注入必须严格经过 `esc()` 或 `jsAttr()` 转义消毒，严禁将动态未过滤输入直接挂载至 `innerHTML`。
4. **零 PII 与密钥凭据防泄漏**：
   - 全仓启用了提交前 `gitleaks` 扫描门禁，CI 自动化运行密钥拦截，严禁包含真实 API Key 或敏感凭证提交。

---

## 🚨 报告安全漏洞 (Reporting a Vulnerability)

如果你在 DeLector 中发现了任何安全漏洞、越权风险或 XSS 注入点，请**不要**直接公开发布 GitHub Issue。

请通过以下途径私下联系维护团队以进行负责任的漏洞披露：

1. **GitHub Private Security Advisory**（首选）：
   进入本仓库的 **Security** 标签页 $\rightarrow$ **Advisories** $\rightarrow$ **Report a vulnerability** 提交私密报告。
2. **电子邮件联系**：
   发送详细的安全分析报告至维护者邮箱：`beianderen@gmail.com`。

### 报告时请包含以下信息：
- 受影响的版本号（如 v5.18.0）；
- 漏洞类型（如 XSS、越权、SSRF、内存破坏等）；
- 详细的概念验证（PoC）或复现步骤；
- 潜在的危害分析与建议的修复方案（若有）。

维护团队将在 **48 小时** 内初步确认漏洞，并在验证完成后优先开发修复分支、发布安全修补版本。
