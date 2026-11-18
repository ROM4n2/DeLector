# 跨平台应用内更新实施计划（ADR-0034 落地）

> **Goal**: 按 ADR-0034 的决策，把「检查到新版本 → 跳 Release 网页」升级为「检查 → 下载 → 校验 → 分平台安装」，平台顺序固定为 **Windows 安装版 → Android → Windows 便携版 → Linux**，macOS 维持现状。`GET /api/update/check` 的 7 键契约**原样冻结**，资产元数据走新增的独立端点。
>
> **实施状态（2026-11-18 同步）**：M0–M5 代码已完成并随 **v5.24.2** 发布（实现链 PR #394，发版修复 #397–#402；Release 产出 5 类资产 + 5 个同名 `.sha256`）。单测与静态守卫已由 CI 执行；Android 系统安装确认、Windows 静默覆盖安装、Windows 便携版换目录、Linux 切换后启动四条真机/真装路径**均未验证**，仍按 §8 停报——不得把「代码已发布」写成「已验证」。
>
> **Tech Stack**: Python 3.11 / FastAPI / httpx / pytest（无 pytest-asyncio）· 原生 JS ES Modules（`// @ts-check` + `tsc --noEmit` 窄口径）· Android Java（Chaquopy + WebView + `PackageInstaller`）· Inno Setup 6 · PyInstaller onedir · GitHub Actions。
>
> **Spec Reference**:
> - 决策正主：`docs/adr/2026-11-17-adr-0034-cross-platform-in-app-update.md`（D1–D8、分平台契约、落地不变式）
> - 事实底稿：`docs/research/2026-11-17-cross-platform-update-strategy.md`
> - 被修订决策：`docs/adr/2026-10-08-adr-0017-android-update-check-notifier.md`（检测链路与 7 键契约继续有效）
> - 现有检测实现：`delector/routes/update.py`
> - 冻结守卫：`tests/test_update_check_endpoint.py`（7 键、`has_update` 三态、结构级「不写库 / 不挂本机闸」）
> - 发布链路：`.github/workflows/build-release.yml:702-736`（资产上传与 Release 正文）
> - 路由注册顺序：`delector/routes/__init__.py:88-115`（分域路由在前、`main` 垫底）
>
> **Global Constraints（MUST，逐条可判定）**
> - **GC1 用户硬约束（优先级最高）**：本机不跑全量测试；不做真机验证；不下载任何安装包或 release 资产；不 push。任何一条都不得为了「验证通过」而绕过。
> - **GC2 验证只认三类证据**：可执行单元测试、仓内 fixture、仓库里已有的 CI 记录。禁止把「代码已写」写成「已验证」，禁止用模拟输出冒充真机/真实安装结论。若某一步必须真下载、真安装或真机运行才能证明，**停下并在里程碑报告里单列**。
> - **GC3 工作区执行边界**：当前工作区处于未受信任状态，**本会话不执行仓内脚本**（含 pytest、`tools/check_*.py`、`node` 探针）。测试以「可被 CI 与用户本机执行」的形态提交；里程碑报告只陈述「已写 / 未运行」，并给出准确执行命令。用户解除信任或授权后，才按 §7 的对点命令补跑。
> - **GC4 契约冻结**：`tests/test_update_check_endpoint.py` **一行都不改**。`/api/update/check` 仍恰好 7 键；`has_update is None ⇔ error_reason is not None`；失败绝不返回 `has_update: false`。新能力只走新端点。
> - **GC5 新路由挂本机闸**：所有会写文件/拉起进程的端点（下载、安装、取消）MUST 调 `_require_localhost`，并**同步**把 `(method, path)` 加进 `tests/test_localhost_guard.py` 的 `PROTECTED_ROUTES` 白名单——该测试对「扫描到但白名单没有」判红（`tests/test_localhost_guard.py:243-253`）。
> - **GC6 新增路由不得塞回 `update.py` 结构守卫的射程**：`update.py` 的源码级守卫禁止出现版本号字面量（正则 `\d+\.\d+\.\d+`，含注释与 docstring）、禁止 DB import、禁止 `_require_localhost`。因此「下载/安装」路由单独成模块，`update.py` 只加只读的 `/artifact`。
> - **GC7 安全锚点不新建**：下载 URL 只接受 `https://`；校验和只认 Release 里的 `*.sha256` 资产；Android 用「下载包签名 == 已安装签名」自锚定；不引入自建更新服务、不做增量更新、不做静默安装。
> - **GC8 零新依赖**：只用 stdlib（`hashlib`/`hmac`/`shutil`/`threading`/`subprocess`）与仓内既有 httpx；不引入 requests/aiohttp。
> - **GC9 数据边界**：更新只碰程序目录/安装目录与临时目录，不碰 `DELECTOR_DATA_DIR` / `%LOCALAPPDATA%\DeLector` 学习数据（ADR-0019）。
> - **GC10 报告节奏**：ADR 定稿已报；本计划定稿报一次；之后**每个端点/平台各自报一次**，不攒到最后。

---

## 0. 里程碑与完成判据

| 里程碑 | 范围 | 完成判据（可判定） | 是否需要停报 |
| --- | --- | --- | --- |
| **M0** | 本计划定稿 | 文件落盘；命名符合 `tools/check_docs_layout.py` 的 `PLAN_RE` | 是（本次） |
| **M1** | Phase 0：CI 生成 `.sha256` + `GET /api/update/artifact` + 单测 + 文档登记 | 新端点 12 键契约有客户端/服务端/缓存/缺资产四类用例；7 键旧测试零改动；docs 布局登记补齐 | 是 |
| **M2** | Windows 安装版：形态判定 → 下载器 → 会话状态机 → 安装拉起 → 前端入口 | 下载器 6 类失败路径各有单测；会话状态机有 `busy`/`failed` 用例；安装命令为纯函数断言 | 是（真装验证停报） |
| **M3** | Android：权限面 → Java 安装器 → JS 桥 → 前端复用状态机 | manifest 权限静态守卫；Java 仅编译级验证；真机安装**停报** | 是（真机停报） |
| **M4** | Windows 便携版：helper 换目录 + 回滚 | helper 脚本生成与路径引号纯函数用例；真替换**停报** | 是 |
| **M5** | Linux：版本目录 + 符号链接原子切换 + 回滚 | 目录布局与切换纯函数用例（tmp_path）；真升级**停报** | 是 |

---

## 1. 基线（2026-11-17 快照）

| 项 | 值 | 来源 |
| --- | --- | --- |
| 版本真相源 | `APP_VERSION = "5.23.5"` | `delector/core/version.py:15` |
| versionCode | `major*10000 + minor*100 + patch` | `delector/core/version.py:22-41` |
| 检测源 | GitHub `releases/latest`，只取 `tag_name` / `html_url` | `delector/routes/update.py:34,82-111` |
| 缓存 | 成功 6h / 失败 60s，服务端全局 | `delector/routes/update.py:41-42,162-183` |
| 7 键契约 | `{current, latest, has_update, page_url, checked_at, cached, error_reason}` | `tests/test_update_check_endpoint.py:29-37` |
| Release 资产 | 5 个：便携 zip / Setup.exe / Linux tar.gz / macOS tar.gz / Android apk | `.github/workflows/build-release.yml:705-709` |
| 资产命名 | `DeLector-<tag>-Windows-x64-Portable.zip`、`-Windows-x64-Setup.exe`、`-Linux-x64.tar.gz`、`-macOS.tar.gz`、`-Android.apk` | 同文件 `:78,194,296,404,545` |
| 安装器 | Inno 6，per-user，`PrivilegesRequired=lowest`，`CloseApplications=yes`，未签名 | `installer/DeLector.iss:34-57` |
| 安装形态判定锚 | 卸载键 `{6F4A2C1E-9B3D-4E7A-8C55-1D2E3F4A5B6C}_is1`、目录内 `unins000.exe` | `installer/DeLector.iss:35` |
| Android | minSdk 24 / targetSdk 34；只出 arm64；无 Play Core / FileProvider / `REQUEST_INSTALL_PACKAGES` | `android/app/build.gradle:145-151`；`android/app/src/main/AndroidManifest.xml:1-34` |
| 本机平台判定 | `is_android()` 已存在（`sys.getandroidapilevel` / `ANDROID_ROOT`） | `delector/core/utils.py:16-18` |
| 前端 chip | 自动检查延迟 3s，仅 `has_update === true` 改 DOM | `static/js/update.js:20-136` |
| 路由注册 | 分域路由在前，`main.router` 最后 | `delector/routes/__init__.py:88-115` |

**行号漂移声明**：以上行号为本计划撰写时的快照；实施时以当前代码重新定位，不照抄改错文件。

---

## 2. 契约设计

### 2.1 资产命名表（唯一真相：CI 产物名）

| `platform` | `channel` | `arch` | 期望资产名 | 可应用内安装 |
| --- | --- | --- | --- | --- |
| `windows` | `installer` | `x64` | `DeLector-<tag>-Windows-x64-Setup.exe` | 是（M2） |
| `windows` | `portable` | `x64` | `DeLector-<tag>-Windows-x64-Portable.zip` | 是（M4） |
| `android` | — | `arm64` | `DeLector-<tag>-Android.apk` | 是（M3，系统确认） |
| `linux` | — | `x64` | `DeLector-<tag>-Linux-x64.tar.gz` | 是（M5） |
| `macos` | — | `x64` | `DeLector-<tag>-macOS.tar.gz` | **否**（D6，仅返回元数据） |

校验和资产名固定为 `<资产名>.sha256`，由 M1 的 CI 步骤生成。若 Release 缺该资产，端点必须报 `checksum_missing`，**不得**降级为「无校验下载」。

### 2.2 `GET /api/update/artifact`（只读，M1）

查询参数（全部走 `Literal` 校验，非法值由 FastAPI 返回 422）：

- `platform`: `windows | linux | macos | android`
- `channel`: `installer | portable`，默认 `portable`；非 `windows` 时忽略
- `arch`: `x64 | arm64`，默认 `x64`；`android` 强制 `arm64`

响应**恰好 12 键**（新契约，独立于 7 键检查契约）：

```json
{
  "platform": "windows",
  "channel": "installer",
  "arch": "x64",
  "version": "5.23.6",
  "asset_name": "DeLector-v5.23.6-Windows-x64-Setup.exe",
  "asset_url": "https://github.com/ROM4n2/DeLector/releases/download/v5.23.6/...",
  "asset_size": 118000000,
  "checksum_url": "https://github.com/ROM4n2/DeLector/releases/download/v5.23.6/....exe.sha256",
  "page_url": "https://github.com/ROM4n2/DeLector/releases/tag/v5.23.6",
  "checked_at": 1763337600,
  "cached": false,
  "error_reason": null
}
```

失败时：`version/asset_name/asset_url/asset_size/checksum_url/page_url` 全为 `null`，`error_reason ∈ {network, timeout, rate_limited, not_found, asset_missing, checksum_missing}`。失败**不得**返回任何「可下载」字段（不降级到最新资产或旧资产）。

不变式（测试逐条钉）：

1. `error_reason is None ⇔ asset_url is not None`（双向）。
2. `asset_url` / `checksum_url` 必须以 `https://` 开头；否则视为 `not_found`。
3. 资产必须来自**同一个** release 响应的 `assets` 数组，且名称精确匹配 §2.1；不做模糊匹配、不按体积猜。
4. 缓存：成功 6h、失败 60s，键独立于 `/check` 的缓存；命中零出网。
5. 端点只读、不写库、不落盘。

### 2.3 下载/安装会话端点（M2 起，桌面三平台共用）

新增模块 `delector/routes/update_apply.py`（**不放进** `update.py`，见 GC6），统一前缀 `/api/update`：

| 方法 | 路径 | 语义 | 本机闸 |
| --- | --- | --- | --- |
| `POST` | `/api/update/download` | 解析本机平台/形态 → 调 `/artifact` 同款解析 → 启动后台下载 | 是 |
| `GET` | `/api/update/download/status` | 返回会话快照（只读） | 是 |
| `POST` | `/api/update/download/cancel` | 取消并删除 `.part` | 是 |
| `POST` | `/api/update/install` | 仅在 `state == "ready"` 时拉起安装/替换并退出应用 | 是 |

会话快照（9 键，前端与测试共用）：

```json
{
  "state": "idle | downloading | verifying | ready | installing | failed",
  "platform": "windows",
  "channel": "installer",
  "version": "5.23.6",
  "downloaded_bytes": 0,
  "total_bytes": 118000000,
  "asset_path": null,
  "error_reason": null
}
```

`error_reason` 追加值：`busy, cancelled, no_space, size_mismatch, checksum_mismatch, write_failed, unsupported, install_failed`。

关键约束：

- 单进程内**只允许一个**更新会话；重入返回 `busy`（不排队、不并发下载）。
- 客户端**不得**传 URL/哈希；后端只接受 `{}`，自己重新解析资产元数据（防 SSRF 与替换）。
- Android 主机（`is_android()`）与 macOS 主机一律返回 `unsupported`：Android 走 Java 桥（M3），macOS 走 Release 页（D6）。
- 安装前的校验顺序固定：`大小 == 元数据 size` → `sha256 == .sha256 资产` → 平台附加校验（签名/版本）。

### 2.4 前端状态机（M2 起）

`static/js/update.js` 现有「仅 `has_update === true` 才改 DOM」的可见性红线不变。新增的更新面板是**用户点击后才出现**的第二层，不污染顶栏版本自证文本。

| 当前态 | 事件 | 下一态 | 可见反馈 |
| --- | --- | --- | --- |
| `idle` | 点击「在应用内更新」 | `downloading` | 进度条 + 取消 |
| `downloading` | 轮询到 `verifying` | `verifying` | 「正在校验」 |
| `downloading` / `verifying` | 轮询到 `failed` | `failed` | 人话原因 + 「打开 Release 页」+ 「重试」 |
| `ready` | 自动（桌面）或用户点「安装」 | `installing` | 「即将重启」 |
| `installing` | 进程退出 | — | 由新进程接管 |
| 任意 | Android 桥不可用 / `unsupported` | `idle` | 只保留 Release 页链接（回退 ADR-0017 行为） |

失败原因映射（禁止回显原始异常）：`no_space→空间不足`、`checksum_mismatch→安装包校验失败`、`size_mismatch→下载不完整`、`install_failed→安装失败，请手动安装`、`cancelled→已取消`。

---

## 3. 阶段 0（M1）：CI 校验和 + 资产元数据端点

### T0.1 · CI 为每个 Release 资产生成 `.sha256`

- **Files**：Modify `.github/workflows/build-release.yml`
- **改动**：在 `Create or Update Release` 之前插入一步（`shell: bash`）：

```yaml
- name: Generate SHA256 checksums
  shell: bash
  run: |
    set -euo pipefail
    cd dist
    shopt -s nullglob
    files=(DeLector-*.zip DeLector-*-Windows-x64-Setup.exe DeLector-*.tar.gz DeLector-*.apk)
    if [ "${#files[@]}" -lt 5 ]; then
      echo "expected at least 5 release assets, got ${#files[@]}" >&2
      exit 1
    fi
    for f in "${files[@]}"; do
      sha256sum "$f" > "$f.sha256"
    done
    cat ./*.sha256
```

- 并把 `dist/DeLector-*.sha256` 加进 `files:` 上传列表（现有 4 条 pattern 之后）。
- **完成判据**：workflow YAML 可被现有 YAML 解析守卫读取（`tests/test_ci_hardening_workflow_wiring.py` 的 workflow 文本断言不回归）；`files:` 含 `.sha256`；步骤在 Release 创建之前。
- **不验证项**：真实发版产物不生成（不 push、不打 tag）。首次真实发版时由 CI 记录确认。

### T0.2 · `GET /api/update/artifact`

- **Files**：
  - Modify `delector/routes/update.py`（只加只读解析与端点；不引入下载/安装）
  - Add `tests/test_update_artifact_endpoint.py`
- **实现要点**：
  1. `_fetch_latest_release` 的返回追加 `assets`（`[{name, url, size}]`），`/check` 的规约路径忽略它——7 键输出不变。
  2. 新增纯函数 `_expected_asset_name(tag, platform, channel, arch)` 与 `_select_asset(assets, name)`；名字精确匹配。
  3. 新增 `_build_artifact_success/_failure` 与独立缓存键（与 `/check` 的 `payload` 分离，但共用 `_cache` 字典，确保现有 fixture 的 `update._cache.clear()` 仍能整体清零）。
  4. 校验和资产存在性检查：`f"{name}.sha256" in asset_names`，否则 `checksum_missing`。
  5. URL 协议校验：非 `https://` → `not_found`。
  6. 端点函数只调 `check_artifact(...)`，不挂本机闸（只读；与 `/check` 同口径）。
  7. **禁止**在 `update.py` 写任何 `x.y.z` 形态的字面量（注释/docstring 也不行），否则 `test_source_has_no_version_literal_and_unifies_on_httpx` 变红。
- **RED 先行**：先写 `tests/test_update_artifact_endpoint.py` 的 8 组用例，跑红（模块无 `check_artifact`）。
- **用例清单**：
  1. 5 个平台/形态组合的资产选中，逐字比对名称。
  2. 响应键集合恰为 12 且与文档一致。
  3. 缺资产 → `asset_missing` 且所有可下载字段为 `null`。
  4. 缺 `.sha256` → `checksum_missing`。
  5. 四类上游失败（timeout / rate_limited / not_found / network）映射不变。
  6. 缓存命中零出网（`FakeFetcher.calls == 1`）+ 失败 60s 后重试。
  7. `TestClient` 真调端点（真 app + 注入假 fetcher），验证跨边界 JSON。
  8. 不变式双向：`(error_reason is None) == (asset_url is not None)`；`https://` 断言。
- **GREEN**：实现后以上全绿；`tests/test_update_check_endpoint.py` **不改文件**且全绿。
- **边界**：只跑对点文件（GC3 下本会话不跑）。

### T0.3 · 文档登记

- **Files**：
  - Modify `docs/research/README.md`：新增「七、发布分发与跨平台更新」小节并登记 `2026-11-17-cross-platform-update-strategy.md`（否则 `tools/check_docs_layout.py::_check_research` 判红）。
  - 本计划文件已符合 `plans/<日期>-<主题>.md`，无需额外索引。
- **完成判据**：`docs/research/README.md` 含该文件名的精确字符串；ADR 索引已含 0034（既有）。

---

## 4. 阶段 1（M2）：Windows 安装版

> 目标：用户点一次「在应用内更新」→ 下载 `Setup.exe` → 校验 → 拉起静默安装 → 应用退出 → 新版本启动。真装不验证（GC1/GC2）。

### T1.1 · 安装形态与平台判定（纯函数）

- **Files**：Add `delector/core/update_host.py`；Add `tests/test_update_host.py`
- **接口**：
  - `detect_platform(android: bool, sys_platform: str) -> Literal["windows","linux","macos","android"]`
  - `detect_arch(machine: str) -> Literal["x64","arm64"]`（`AMD64/x86_64 → x64`，`arm64/aarch64 → arm64`，其余 `x64`）
  - `detect_windows_channel(install_dir: Path, uninstall_key_exists: Callable[[str], bool]) -> Literal["installer","portable"]`
    - `installer` ⇔ `install_dir/unins000.exe` 存在 **或** 卸载键存在（键名常量取自 `installer/DeLector.iss:35`）
- **RED/GREEN**：`tmp_path` 造 `unins000.exe`；注入假注册表读取器；Android 优先于 `sys.platform`（Chaquopy 下 `sys.platform == "linux"` 的陷阱）。

### T1.2 · 下载器（可断点、可取消、校验）

- **Files**：Add `delector/core/update_download.py`；Add `tests/test_update_download.py`
- **接口（全部可注入传输，零真实网络）**：
  - `parse_sha256_asset(text: str, expected_name: str) -> str | None`：兼容 `hex  name` / `hex *name`，只认 64 位 hex
  - `sha256_file(path: Path) -> str`（分块读，1MB）
  - `verify_sha256(path, expected_hex) -> bool`（`hmac.compare_digest`）
  - `plan_range(part_path: Path, expected_size: int) -> tuple[int, dict]`：已有 `.part` 时给出 `Range: bytes=<n>-`
  - `download(asset_url, expected_size, dest_dir, *, transport, cancel_event, on_progress) -> Path`
- **行为契约**：
  1. 先写 `<name>.part` → 校验大小 → 校验 sha256 → `os.replace` 为正式名。
  2. 服务端忽略 Range 返回 200：丢弃 `.part` 从头写（不拼接、不信任长度）。
  3. 中断/取消：保留 `.part`（取消则删除），状态 `cancelled`。
  4. 空间预检：`shutil.disk_usage(dest).free < expected_size + 64MB` → `no_space`（不启动下载）。
  5. 任何非 2xx/3xx：`network`；401/403/429：`rate_limited`；404：`not_found`。
- **RED/GREEN**：6 类失败路径 + 续传成功各一条用例。

### T1.3 · 会话状态机

- **Files**：Add `delector/core/update_session.py`；Add `tests/test_update_session.py`
- **接口**：
  - `UpdateSession(resolver, downloader, clock)`：`start(version) -> snapshot`、`cancel()`、`snapshot()`
  - 状态迁移严格按 §2.3；`busy` 当且仅当已有 `downloading|verifying|installing`
  - 线程安全：`threading.Lock` 保护快照与迁移；下载线程只写状态
- **RED/GREEN**：注入可控下载器（事件阻塞），断言 `idle→downloading→verifying→ready`、`cancel→failed(cancelled)`、重复 `start→failed(busy)`、异常→`failed` 且不抛到路由。

### T1.4 · 本机动作路由

- **Files**：
  - Add `delector/routes/update_apply.py`
  - Modify `delector/routes/__init__.py`（注册 `update_apply.router`，位置在 `update.router` 之后、`settings.router` 之前）
  - Modify `tests/test_localhost_guard.py`（`PROTECTED_ROUTES` 增加 4 条 `POST`）
  - Add `tests/test_update_apply_routes.py`
- **接口**：§2.3 的四个端点；`/install` 只接受 `state == "ready"`，否则 409。
- **RED/GREEN**：非本机请求 403（复用现有 client 夹具写法）；状态不符 409；`unsupported` 平台 400；`TestClient` 真调。

### T1.5 · Windows 安装拉起

- **Files**：Add `delector/core/update_apply.py`；Add `tests/test_update_apply.py`
- **接口**：
  - `installer_command(exe: Path) -> list[str]` → `[str(exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]`
  - `spawn_installer(exe, *, popen=subprocess.Popen)`：`shell=False`，Windows 下 `creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`
  - `schedule_exit(delay_s, exit_fn)`：延迟退出，让安装器拿到文件锁
- **RED/GREEN**：命令逐字断言；`popen` 注入断言参数与 `shell=False`；结构断言禁止 `os.system`。
- **停止点**：真实 `/VERYSILENT` 覆盖安装与重启，**必须**在 Windows 机器或 CI（现有 `build-release.yml:177-188` 只证明「安装器能静默装」，不证明「应用内拉起能装」）上验证 → 里程碑报告单列，不在本机模拟。

### T1.6 · 前端入口

- **Files**：Modify `static/js/update.js`；Modify `static/js/api-types.js`（新增端点 typedef）；Add `tests/test_update_flow_probe.py`（`node:vm` 探针，沿用仓内前端探针形态）
- **行为**：`has_update === true` 时 chip 内提供「在应用内更新」按钮；点击 → `POST /api/update/download` → 轮询 `/status`；失败展示人话 + Release 页退路。无桌面能力（桥/端点 `unsupported`）时**只保留**现有链接。
- **RED/GREEN**：状态机纯函数在 `node:vm` 中跑六条迁移；`/api/update/...` 字面量必须被 `tools/check_frontend_api_contract.py` 识别为已注册路由。

---

## 5. 阶段 2（M3）：Android

> 目标：Python 复用下载器把 APK 落到应用私有目录并校验；Java 只做「签名/版本预检 + PackageInstaller 会话」。系统确认不可省。

### T2.1 · 权限面与静态守卫

- **Files**：Modify `android/app/src/main/AndroidManifest.xml`（加 `REQUEST_INSTALL_PACKAGES`）；Add `tests/test_android_update_permission.py`
- **RED/GREEN**：测试读取 manifest 文本/AST，断言权限存在且**只**新增这一条（防止顺手加 DownloadManager/前台服务）。变异：删除权限行 → 红。

### T2.2 · Java 安装器

- **Files**：Add `android/app/src/main/java/org/delector/app/ApkInstaller.java`；Modify `MainActivity.java`（注册 `DeLectorUpdate` 桥）
- **职责（只做三件事）**：
  1. `canRequestPackageInstalls()`（API 26+）→ 否则返回 `NEED_UNKNOWN_SOURCES` 并给出 `ACTION_MANAGE_UNKNOWN_APP_SOURCES` Intent。
  2. 路径白名单：只接受规范化后位于 `getFilesDir()/updates/` 下的 `.apk`；其余 `BAD_PATH`。
  3. `PackageArchiveInfo` 读包名/versionCode/签名 → 与已安装应用比对：包名不符 `PACKAGE_MISMATCH`、versionCode 不增 `VERSION_NOT_INCREASED`、签名不符 `SIGNATURE_MISMATCH`；通过后开 `PackageInstaller.Session`，把文件流写进会话并提交，回传 `PENDING_USER_ACTION / INSTALL_FAILED_*`。
- **不做**：下载、FileProvider、DownloadManager、静默安装、后台服务。
- **验证边界**：本会话**不编译、不真机**。只能声明「代码已写 + Java 侧仅由 CI 的 Android 构建做编译级验证」。运行时行为（会话确认、签名比对、OEM 额外确认）→ 停止报告，等真机。

### T2.3 · 前端接线

- **Files**：Modify `static/js/update.js`
- **行为**：`window.DeLectorUpdate` 存在时，下载完成后把 `asset_path` 交给桥 `install(path)`；桥返回 `NEED_UNKNOWN_SOURCES` 时展示「去设置允许安装」；其余失败按 §2.4 映射。
- **RED/GREEN**：`node:vm` 注入假桥，断言「无桥 → 只显示链接」「有桥 → 调一次 install」；不得出现「静默安装」文案（文本断言）。

### T2.4 · 后端边界

- **Files**：Modify `delector/routes/update_apply.py`
- **行为**：`is_android()` 为真时 `/download` **允许**（复用 Python 下载器与校验，落 `DELECTOR_DATA_DIR/updates/`）；`/install` 返回 `unsupported` —— 安装由 Java 桥完成；`/artifact` 返回 APK 元数据供前端显示体积。
- **RED/GREEN**：注入 `is_android` 假值，断言下载目标为 `("android","portable","arm64")`；`/install` 在 Android 快照下 400。

---

## 6. 阶段 3（M4）：Windows 便携版

### T3.1 · 解压与目录交换计划（纯函数）

- **Files**：Add `delector/core/update_portable.py`；Add `tests/test_update_portable.py`
- **接口**：
  - `install_root(executable: Path) -> Path`（`DeLector.exe` 所在目录）
  - `build_apply_script(pid, source_dir, target_dir, log_path) -> str`：生成 PowerShell 脚本文本
    - 等待 PID：`Wait-Process -Id <pid> -ErrorAction SilentlyContinue`
    - 备份：`Rename-Item target target.bak`；失败则 `Restore`
    - 复制：`Copy-Item source/* target -Recurse -Force`
    - 重启：`Start-Process target/DeLector.exe`
    - 清理：成功后删 `target.bak` 与临时目录
  - `is_writable_root(root: Path) -> bool`（探测写权限，失败 → `unsupported`，不冒险替换）
- **RED/GREEN**：脚本内所有路径必须被单引号包裹且 `'` 转义为 `''`（路径含空格/单引号用例）；`is_writable_root` 用只读目录 fixture。
- **停止点**：真实目录替换与重启 → 停止报告，需 Windows 机器。

---

## 7. 阶段 4（M5）：Linux

### T4.1 · 版本目录 + 符号链接

- **Files**：Add `delector/core/update_linux.py`；Add `tests/test_update_linux.py`
- **受管布局**：`${XDG_DATA_HOME:-~/.local/share}/DeLector/versions/<version>/` + `${XDG_BIN_HOME:-~/.local/bin}/DeLector` → 指向 `versions/<version>/DeLector` 的符号链接。
- **接口**：
  - `managed_root(env) -> Path`
  - `plan_switch(root, current_exe, version) -> SwitchPlan | None`：当前可执行文件不在受管版本目录下 → `None`（拒绝自替换，回退 Release 页）
  - `apply_switch(plan)`：先建临时符号链接再 `os.replace`（原子）；旧版本目录保留一份用于回滚
  - `rollback(plan)`：把链接切回上一版本
- **RED/GREEN**：`tmp_path` 造两个版本目录，断言切换后链接指向新版本、旧目录仍在；非受管路径 → `None`。
- **停止点**：真实 Linux 启动新版本 → 停止报告（本机为 Windows）。

---

## 8. 验证矩阵（含不可验证项）

| 项 | 证据类型 | 本会话状态 | 说明 |
| --- | --- | --- | --- |
| 7 键契约不回归 | 既有单测（零改动） | CI 已执行（PR #394） | `tests/test_update_check_endpoint.py` |
| `/artifact` 契约与失败语义 | 新增单测 + TestClient | CI 已执行（PR #394） | 假 fetcher，零网络 |
| 缓存/TTL | 新增单测 | CI 已执行（PR #394） | 与 `/check` 同口径 |
| 下载器续传/校验/取消 | 新增单测 + 假传输 | CI 已执行（PR #394） | 零真实网络、零资产下载 |
| 会话状态机 | 新增单测 | CI 已执行（PR #394） | 注入事件 |
| 安装命令/脚本生成 | 新增单测 + 结构断言 | CI 已执行（PR #394） | 不拉起进程 |
| Android 权限面 | 静态测试 | CI 已执行（PR #394） | manifest 文本/AST |
| Android 安装运行时 | — | **未验证** | 需真机；与 PROJECT_OVERVIEW 活项 2 合并执行 |
| Windows 静默安装真装 | CI 仅覆盖「安装器可静默装」 | **未验证** | 应用内拉起需 Windows 机器 |
| Windows 便携版目录替换 | — | **未验证** | 需 Windows 机器 |
| Linux 符号链接切换后启动 | — | **未验证** | 需 Linux 机器 |
| 真实 `.sha256` 生成 | v5.24.2 Release 资产清单 | **已产出**（5 个 `.sha256`） | 内容未逐字节复核 |

对点执行命令（用户授权后）：

```powershell
python -m pytest -q tests/test_update_check_endpoint.py tests/test_update_artifact_endpoint.py tests/test_update_host.py tests/test_update_download.py tests/test_update_session.py tests/test_update_apply_routes.py tests/test_update_apply.py tests/test_update_portable.py tests/test_update_linux.py tests/test_update_flow_probe.py tests/test_update_chip_ui.py tests/test_android_update_permission.py tests/test_localhost_guard.py
python tools/check_docs_layout.py
python tools/check_frontend_api_contract.py
```

**不跑全量 pytest**；静态闸只跑与改动直接相关的两个脚本。

---

## 9. 风险与回滚

| 风险 | 影响 | 缓解 | 回滚 |
| --- | --- | --- | --- |
| 资产命名漂移（CI 改名） | `asset_missing`，更新不可用 | §2.1 与 workflow 双向登记；单测逐字钉名 | 只影响新端点，`/check` 与 Release 页仍可用 |
| `.sha256` 未上传 | 端点 `checksum_missing`，拒绝下载 | CI 步骤失败即发版失败（`set -euo pipefail`） | 关闭前端入口即回到 ADR-0017 行为 |
| 下载中断/被杀进程 | 更新失败，旧版可用 | `.part` 续传 + 取消；状态机不停留在 `downloading` | 删除临时目录；重试 |
| 校验和不符 | 拒绝安装 | `hmac.compare_digest`；不符即 `checksum_mismatch` | 保留旧版；引导 Release 页手工下载 |
| 安装器被 SmartScreen 拦截 | 用户需多一步确认 | 文档如实说明「未签名」；不承诺零提示 | 用户取消 → 旧版继续可用 |
| Inno `CloseApplications` 关不掉应用 | 安装失败 | 应用在拉起安装器后主动延迟退出 | 安装器退出码非 0 → `install_failed` |
| 便携版替换到一半失败 | 目录损坏 | helper 先备份再复制；失败回滚 `.bak` | 手动改名回滚 |
| Linux 非受管布局 | 无法自替换 | 直接拒绝（`None`）→ Release 页 | 不改变现有「解压即用」语义 |
| Android 签名不符 | 覆盖安装失败 | 安装前预检 + 系统兜底 | 旧版保留；**绝不引导卸载**（会清数据） |
| Android 未知来源被拒 | 安装不进行 | 引导到系统设置页，不循环弹窗 | 旧版继续可用 |

---

## 10. 报告模板（每个里程碑必填）

1. 里程碑编号与范围。
2. 实际改动文件清单（逐文件）。
3. 新增/修改的测试（文件 + 用例数）。
4. 已运行 / 未运行的验证，原文命令。
5. 不可验证项（若命中 GC2 停止条件，单列并说明需要什么环境）。
6. 与 ADR-0034 不变式的逐条对照（7 键未动、失败不伪装、URL 仅 https、数据目录未碰）。
