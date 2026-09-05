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
静态检查:  python -m pyflakes server.py syntax_tree.py start.py linguistics.py
```

**Git 推送通道**：这台机器上 HTTPS 连 fetch 都会失败（`schannel: failed to receive handshake`），
`origin` 已指向 `ssh://git@ssh.github.com:443/ROM4n2/DeLector.git`（22 端口时通时不通，443 稳定）。
`gh` CLI 走自己的 HTTPS API 认证，不受影响。

---
