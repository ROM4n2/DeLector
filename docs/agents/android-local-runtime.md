# DeLector Android 本机运行与模拟器使用（Agent 深读文档）

> 2026-11-05 按本机实测沉淀；维护约定同 `architecture.md` / `ops.md`（就地修改、不追加副本）。
> **本文所有路径与数字均为 2026-11-05 实测值**，不写“大概是”。换机器或换 AVD 后请重新测量并更新。

---

## 1. 环境常量（实测）

| 项 | 值 | 备注 |
| --- | --- | --- |
| SDK | `D:\Android\sdk` | `platforms\android-34`（另有 `android-37.0`）、`build-tools\34.0.0`（另有 `36.0.0`）、`platform-tools\adb.exe`、`emulator\emulator.exe`（23,458,968 B） |
| AVD 名 | `Medium_Phone_API_37.0` | 由 `D:\Android\avd\Medium_Phone_API_37.0.ini`（110 B）解析；实际目录 `D:\Android\avd\Medium_Phone.avd` |
| AVD 家目录 | `D:\Android\avd` | 用户级环境变量 `ANDROID_AVD_HOME` 已指向此处 |
| AVD 系统镜像 | `system-images\android-37.0\google_apis_playstore\x86_64\` | `config.ini` 的 `abi.type=x86_64`、`hw.cpu.ncore=16`、`hw.ramSize=2048`、`disk.dataPartition.size=10G` |
| AVD 关键文件 | `config.ini` 1,281 B；`userdata-qemu.img.qcow2` 1,960,771,584 B；`snapshots\default_boot\ram.img` 4,295,032,832 B | 数字为字节 |
| Gradle | `D:\Android\gradle\wrapper\dists\gradle-8.6-bin\afr5mpiioh2wthjmwnkmdsd5w\gradle-8.6\bin\gradle.bat` | **仓库没有 `gradlew`**（根目录与 `android\` 下均 `Test-Path` = False）；只能调本机 dists |
| 镜像配置 | `D:\Android\gradle\init.gradle`（3,832 B） | 1.5 s 探针 → 探通才插入阿里云镜像（google / public / gradle-plugin），否则直接走官方仓库；只覆盖**依赖仓库** |
| wheel 本地供给 | `D:\Android\chaquo-wheels\arm64-v8a`、`D:\Android\chaquo-wheels\x86_64` | 由 `android\local.properties` 的 `python.pipFindLinks` 驱动；该文件被 `.gitignore` 挡（`android/local.properties`），**仓内不留任何字面路径** |

> `init.gradle` **管不到 Gradle wrapper 自身的分发**：`distributionUrl` 由 wrapper 自己下载，镜像配置对它无效。
> 想加速 wrapper 只能改 `distributionUrl` 指向国内镜像（并核对 SHA），或像本机这样**预置 dists 目录**。

---

## 2. 启动 / 关闭 / 确认

**启动**（PowerShell，复制执行）：

```powershell
& "D:\Android\sdk\emulator\emulator.exe" -avd Medium_Phone_API_37.0
```

**等设备就绪**（另一终端；出现 `emulator-5554  device` 才算就绪，`offline` 不算）：

```powershell
& "D:\Android\sdk\platform-tools\adb.exe" devices
```

**关闭**：

```powershell
& "D:\Android\sdk\platform-tools\adb.exe" -s emulator-5554 emu kill
```

**确认已关**（两条都为空/无输出才算关干净）：

```powershell
& "D:\Android\sdk\platform-tools\adb.exe" devices
Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue
```

- **首次冷启动会生成 userdata**：耗时与磁盘占用明显更大（本机 `userdata-qemu.img.qcow2` 已达 1,960,771,584 B；`ram.img` 4,295,032,832 B）。
- **加速自检**（实测输出）：

  ```text
  > & "D:\Android\sdk\emulator\emulator.exe" -accel-check
  accel:
  0
  WHPX(10.0.26200) is installed and usable.
  accel
  ```

  `emulator-check hyper-v` 返回码 **2** 并输出 `Hyper-V is enabled` 是**正常状态**，不是错误——Android Studio 日志里会反复出现，别误判。

**当前状态（2026-11-05 交接实测）**：`adb devices` 已不列出 `emulator-5554`，`Get-Process qemu-system-x86_64` 为空；模拟器由用户自行关闭。任何人再启动前先到 §4 登记。

---

## 3. 构建与装机的最小序列（顺序不能乱）

> 前提：`tools/sync_android_sources.py` 随 **PR #233**（`fix/android-python-sync`）引入；在 #233 合并前 `master` 上没有这个文件，需先切到该分支或按 CI 的 Sync 语义手工拷贝。

**1）先同步 Python 源码与模型**（**必须先跑**；否则打出 22 B 的空 `app.imy`，装机能成功，但启动报 `ModuleNotFoundError: No module named 'start'`）：

```powershell
& "d:\Code\DeLector\.venv\Scripts\python.exe" tools\sync_android_sources.py
```

**2）构建 emulator debug 包**：

```powershell
& "D:\Android\gradle\wrapper\dists\gradle-8.6-bin\afr5mpiioh2wthjmwnkmdsd5w\gradle-8.6\bin\gradle.bat" assembleEmulatorDebug
```

**3）装机**：

```powershell
& "D:\Android\sdk\platform-tools\adb.exe" -s emulator-5554 install -r android/app/build/outputs/apk/emulator/debug/app-emulator-debug.apk
```

**4）启动主 Activity**：

```powershell
& "D:\Android\sdk\platform-tools\adb.exe" -s emulator-5554 shell am start -W -n org.delector.app.emulator/org.delector.app.MainActivity
```

**5）等 40–50 秒后验活**：

```powershell
& "D:\Android\sdk\platform-tools\adb.exe" -s emulator-5554 shell pidof org.delector.app.emulator
& "D:\Android\sdk\platform-tools\adb.exe" -s emulator-5554 logcat -d | findstr /C:"No module named"
```

`pidof` 必须非空；`findstr` 必须无命中。

**6）接口探针**（本次实测走 `adb forward` + PowerShell，不是设备内 curl）：

```powershell
& "D:\Android\sdk\platform-tools\adb.exe" -s emulator-5554 forward tcp:8000 tcp:8000
(Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/settings" -UseBasicParsing).Content
(Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/syntax/spacy-status" -UseBasicParsing).Content
& "D:\Android\sdk\platform-tools\adb.exe" -s emulator-5554 forward --remove tcp:8000
```

本次实测返回：`/api/settings` 的 `nlp_engine` 为 `pure_python`；`/api/syntax/spacy-status` 为 `{"path":"spacy","error":""}`。两者不一致的原因见 §5 第 1 条。

---

## 4. 模拟器使用登记（硬规则）

> **任何会话启动模拟器前先在本表登记一行；用完后在同一行补“已关闭”。未登记视为违规。**

| 日期 | 使用方 | 目的 | 是否已关闭 |
| --- | --- | --- | --- |
| 2026-11-05 | deepseek-v4.1-flash__trae | Android 源码同步修复 + pure_python 降级排查 | 用户将自行关闭（交接实测已关闭） |

---

## 5. 已知问题与待决策

1. **`pure_python` 降级（未修复，待用户批准）**
   `delector/nlp_engine/processor.py:240-246` 的 `elif _android_runtime:` 按平台硬编码 `nlp = None`，主路径走纯 Python。模型与 dist-info 都在 APK 内且可加载（设备上 `/api/syntax/spacy-status` = `{"path":"spacy","error":""}`）；**无 ADR 记录**该降级；`tests/test_server_android_fallback.py` 当前**断言 `ENGINE=pure_python`**，等于把降级钉成规格。最小改动（照原方案，未执行）：
   1. 删除 `processor.py:240-246` 的 `elif _android_runtime:` 整段，让 Android 与桌面一样走 `_LazyNlp()`（导入期仍不 `spacy.load`，冷启动不受影响）。
   2. 在 `processor.py:96-114` 的 `_load_model_with_autodownload()` 里，Android 时不再尝试 `spacy.cli.download`（本地三级回退失败就抛 `RuntimeError`，保持“硬失败不静默”）；可复用现成的 `try_load_nlp_no_download()` 语义。
   3. 同步更新两处过时文字：`processor.py:241-243` 注释与 `docs/agents/architecture.md:120-124` 的“没有 dist-info”。
   4. 更新测试 `test_android_never_downloads_model_at_import`：它当前断言 `ENGINE=pure_python`；应改为“导入期不加载、绝不下载”，并允许首次使用时加载为 `spacy`。
   5. 重建 → 装机 → 验证：`/api/settings` 的 `nlp_engine` 从 `pure_python` 变 `spacy`，`nlp_engine_detail` 出现 `de_core_news_sm(module.load)` 或 `de_core_news_sm`，冷启动 `TotalTime` 不显著变差。
2. **`delector/nlp_engine/syntax_tree.py:71-89` 裸 `spacy.load` 无三级回退**：设备上碰巧成功（dist-info 在包内），换打包方式会 `E050`。
3. **device APK 无真机验证**：本机没有 arm64 设备，`assembleDeviceDebug` 只验证到构建产物层面。
4. **`docs/agents/architecture.md:120-124` 已过时**：仍写“Android 上 `spacy.load("名称")` 必然报 E050、靠 `importlib` 回退”，与 2026-11-05 实测冲突；已在该段加标注，原结论未改。
5. **PR #233 未合并**：分支 `fix/android-python-sync`，head `2a6e6ba`，CI 全绿；`tools/sync_android_sources.py` 只在那个分支上。

---

## 6. 证据在哪、什么时候删

- `D:\Code\_artifacts\android-sync-20261105\`：本次同步修复的重建/装机/logcat/截图/验闸证据，`NOTES.md` 已写（含三件证明与每个文件的删除时机）。
- `D:\Code\_artifacts\apk-smoke-20261105\`：旧空包（`app.imy` = 22 B）那次事故的装机与 `ModuleNotFoundError` 证据。
- 大二进制（>50 MB APK）已按 `_artifacts` 规则删实物留文本，SHA/字节见 `android-sync-20261105\big-binaries.txt`。
