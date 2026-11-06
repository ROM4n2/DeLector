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

本次实测返回（**修复前**状态）：`/api/settings` 的 `nlp_engine` 为 `pure_python`；`/api/syntax/spacy-status` 为 `{"path":"spacy","error":""}`。两者不一致是"主路径纯 Python + 句法专线 spaCy"两层语义造成的；ADR-0028 已决定统一为 spaCy（见 §5 第 1 条）。

---

## 4. 模拟器使用登记（硬规则）

> **任何会话启动模拟器前先在本表登记一行；用完后在同一行补“已关闭”。未登记视为违规。**

| 日期 | 使用方 | 目的 | 是否已关闭 |
| --- | --- | --- | --- |
| 2026-11-05 | deepseek-v4.1-flash__trae | Android 源码同步修复 + pure_python 降级排查 | 用户将自行关闭（交接实测已关闭） |
| 2026-11-06 | deepseek-v4.1-flash__trae | T5/T6 Android spaCy 实测（改造前 `aec79f3` vs master `e169999`） | 未关闭（测量中） |

---

## 5. 已知问题与待决策

1. **`pure_python` 降级（已由 ADR-0028 改为 spaCy 主路径，已实施）**
   `delector/nlp_engine/processor.py:240-246` 的 `elif _android_runtime:` 按平台硬编码 `nlp = None`，主路径走纯 Python——这是**修复前状态**。ADR-0028（`docs/adr/2026-11-06-adr-0028-android-main-path-spacy-lazy-load.md`）已改为 spaCy 主路径：与桌面同口径，惰性加载 + 本地三级回退 + 失败硬失败（`spacy(加载失败)`）+ 禁止运行期 `spacy.cli.download`。截至 2026-11-06：**已实施并合并 `master`**（`af027f8` 主路径、`2f79ccb` 共用加载器、`73d5442` 句法专线硬失败；PR #237 合并 commit `7073bac`）；`tests/test_server_android_fallback.py` 的断言已是 `assert "ENGINE=spacy" in out`；**T5/T6 Android 测量未执行**。
   仍保留的硬约束：导入期不加载（启动页预算）、运行期禁止 `spacy.cli.download`（不联网/不起 pip 子进程）。**已删除**“无 dist-info ⇒ `spacy.load` 必失败”这一失效理由：APK 内含 `de_core_news_sm-3.8.0.dist-info/`（12 个文件），设备上 `spacy.load` 可成功。
   纯 Python 的能力缺口（修复前）：`case` 恒空、无 `dep/head_*`、`topology` 仅 `mittelfeld`、`clause_tree` 单节点 `hauptsatz`、可分动词不识别；其中 `pos` 启发式会**标错**词性，判据"宁漏勿错"因此否决保留纯 Python。
   同一进程的两层语义（主路径纯 Python；句法专线 `syntax_tree.get_spacy_nlp()` 按需加载真模型）**已消除**（`2f79ccb`）：两端共用同一加载器与失败语义。
2. **`syntax_tree.get_spacy_nlp()` 裸 `spacy.load`（已消除，`2f79ccb`）**：现收敛到统一加载器（2026-11-06 实现迁至 `model_loader.py`，`processor` 只保留转发入口），共用三级回退与 Android 禁下载门控；A7（`73d5442`）起 `analyze_syntax_tree` 也改为硬失败，不再回退纯 Python。
3. **device APK 无真机验证**：本机没有 arm64 设备，`assembleDeviceDebug` 只验证到构建产物层面。
4. **`docs/agents/architecture.md:120-127` 已修正**：不再声称“Android 上按名称加载模型必然失败”，改为与 2026-11-05 实测一致（APK 内含 dist-info、`spacy.load` 可成功），并指向 ADR-0028。

---

## 6. 证据在哪、什么时候删

- `D:\Code\_artifacts\android-sync-20261105\`：本次同步修复的重建/装机/logcat/截图/验闸证据，`NOTES.md` 已写（含三件证明与每个文件的删除时机）。
- `D:\Code\_artifacts\apk-smoke-20261105\`：旧空包（`app.imy` = 22 B）那次事故的装机与 `ModuleNotFoundError` 证据。
- 大二进制（>50 MB APK）已按 `_artifacts` 规则删实物留文本，SHA/字节见 `android-sync-20261105\big-binaries.txt`。
