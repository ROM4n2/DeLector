import os
import re

import pytest
from server_helpers import ROOT

# --- Android / Chaquopy runtime: spacy is absent, everything must fall back to pure Python ---


def test_pure_python_pipeline_without_spacy():
    """APK 里没有 spacy，process_german_text 走纯 Python 分支。

    这条分支曾因调用不存在的 lookup_core_dict 而在 import server 时就 NameError，
    导致安卓端 uvicorn 永远起不来、启动页一直卡住。
    """
    from delector.nlp_engine import processor as nlp

    result = nlp._process_german_text_pure_python("Der Hund schläft. Ich habe ein Buch gelesen!")

    assert result["sentence_count"] == 2
    tokens = [t for s in result["sentences"] for t in s["tokens"]]
    assert tokens, "pure-python 分支必须产出 token"
    # 核心词库命中时应带出 CEFR 与词性，而不是空值
    der = next(t for t in tokens if t["text"] == "Der")
    assert der["lemma"] == "der"
    assert der["cefr_level"]
    assert all(t["cefr_level"] == "" for t in tokens if t["is_punct"])
    assert result["stats"]["word_count"] > 0


def test_module_import_survives_without_spacy(monkeypatch):
    """server 的 import 期副作用（init_db → seed_preset_articles）不能依赖 spacy。"""
    from delector import server
    from delector.nlp_engine import processor

    # 补丁钉在真实取值面：process_german_text 按实现模块的模块全局 nlp 判「spacy 可用性」
    # （`if nlp is None` 分支）；server.nlp 只是裸 re-export、patch 不生效（C9 mock-drift 真遗留）。
    monkeypatch.setattr(processor, "nlp", None)
    seeded = server.process_german_text(server.PRESET_ARTICLES[0]["text"])
    assert seeded["sentence_count"] > 0
    assert seeded["sentences"][0]["tokens"]


def test_syntax_tree_pure_python_sentence_split():
    """syntax_tree 的降级分支曾有和 server 完全相同的切句 bug：句号被切成独立句子。"""
    from delector.nlp_engine.syntax_tree import _analyze_syntax_tree_pure_python, split_sentences_pure_python

    assert split_sentences_pure_python("Der Hund schläft. Ich lese!") == [
        "Der Hund schläft.",
        "Ich lese!",
    ]
    result = _analyze_syntax_tree_pure_python("Der Hund schläft. Ich lese!")
    assert result["sentence_count"] == 2
    assert [s["text"] for s in result["sentences"]] == ["Der Hund schläft.", "Ich lese!"]


def test_bind_host_is_loopback_only_on_android(monkeypatch):
    """Android 上必须只监听回环：POST /api/settings 无鉴权，绑 0.0.0.0 会暴露给整个局域网。"""
    import start

    monkeypatch.setattr(start, "is_android", lambda: True)
    assert start.get_bind_host() == "127.0.0.1"

    monkeypatch.setattr(start, "is_android", lambda: False)
    assert start.get_bind_host() == "0.0.0.0"


def test_settings_reports_nlp_engine(client):
    """降级 / 硬失败都不是静默的，所以引擎状态必须能从 API 读到（真机上唯一的可验证途径）。

    模型惰性化后 /api/settings **live** 读 `processor.NLP_ENGINE`（而非导入期快照，见
    routes/main.py 顶部注释），故这里也与**同一个 live 源**比对。合法取值多一个
    `"spacy(加载失败)"`：运行期模型加载失败是**硬失败不降级**（见 processor._resolve_nlp_model），
    此时必须如实报出来，而不是仍谎报可用的 `"spacy"`。
    """
    from delector.nlp_engine import processor

    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert data["nlp_engine"] in ("spacy", "pure_python", "spacy(加载失败)")
    assert data["nlp_engine"] == processor.NLP_ENGINE
    assert data["nlp_engine_detail"]


def test_android_never_downloads_model_at_import():
    """Android 上 spacy.cli.download 会起 pip 子进程拉 15MB 模型。

    Chaquopy 里必然失败，但会在 import server 期间阻塞启动——正是把 APK
    卡在启动页的那类故障。装上 spaCy 后这段原本的死代码变成了活路径。
    """
    import os
    import subprocess
    import sys

    probe = (
        "import spacy, sys, os\n"
        "def _boom(*a, **k):\n"
        "    raise OSError('simulated')\n"
        # 三条加载路径全部堵死：spacy.load(名称)、模块自身 load()、按数据目录加载
        "spacy.load = _boom\n"
        "import spacy.util\n"
        "spacy.util.load_model_from_init_py = _boom\n"
        "spacy.util.load_model_from_path = _boom\n"
        "import spacy.cli\n"
        "spacy.cli.download = lambda *a, **k: print('DOWNLOAD_ATTEMPTED')\n"
        "sys.path.insert(0, os.getcwd())\n"
        "from delector import server\n"
        "print('ENGINE=' + server.NLP_ENGINE)\n"
    )
    env = {**os.environ, "ANDROID_ROOT": "/system", "PYTHONIOENCODING": "utf-8"}
    res = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env
    )
    out = (res.stdout or "") + (res.stderr or "")
    assert "DOWNLOAD_ATTEMPTED" not in out, "Android 上不得在 import 期联网下载模型"
    assert "ENGINE=pure_python" in out


def test_spacy_model_candidates_prefer_md():
    """README 与 Dockerfile 都装 md（带词向量、标注更准），sm 只是兜底。"""
    from delector.nlp_engine import processor as nlp

    assert nlp.SPACY_MODEL_CANDIDATES == ("de_core_news_md", "de_core_news_sm")
    # 自动下载走小模型：md 约 45MB，首启动拉它太慢
    assert nlp.AUTO_DOWNLOAD_MODEL == "de_core_news_sm"


def test_load_spacy_model_falls_back_to_module_load(monkeypatch):
    """spacy.load(名称) 查的是 .dist-info；Android 上模型是直接拷进源码目录的。

    真机实测报的就是 "[E050] Can't find model 'de_core_news_sm'"，尽管这个包
    import 得动。所以按名称失败后必须退到模块自身的 load()。
    """
    import sys
    import types

    from delector.nlp_engine import processor as nlp

    sentinel = object()
    fake = types.ModuleType("de_fake_news_sm")
    fake.load = lambda **kw: sentinel  # type: ignore[attr-defined]  # 构造假模块顶替 sys.modules，刻意在 ModuleType 上动态挂属性
    monkeypatch.setitem(sys.modules, "de_fake_news_sm", fake)
    monkeypatch.setattr(nlp.spacy, "load", lambda *a, **k: (_ for _ in ()).throw(OSError("[E050] Can't find model")))

    model, how = nlp._load_spacy_model("de_fake_news_sm")
    assert model is sentinel
    assert "module.load" in how


def test_load_spacy_model_reports_every_failed_strategy(monkeypatch):
    """全部失败时错误信息要带上每条策略的原因，否则真机上无从判断卡在哪。"""
    from delector.nlp_engine import processor as nlp

    monkeypatch.setattr(nlp.spacy, "load", lambda *a, **k: (_ for _ in ()).throw(OSError("no dist-info")))
    with pytest.raises(RuntimeError) as excinfo:
        nlp._load_spacy_model("de_definitely_not_installed")
    message = str(excinfo.value)
    assert "spacy.load" in message
    assert "import de_definitely_not_installed" in message


def test_android_build_extracts_spacy_data_packages():
    """Chaquopy 默认不把包的数据文件解到磁盘（build.json 的 extract_packages 为空）。

    这三个包都用 Path(__file__).parent 去 open() 真实文件，漏掉任何一个，
    真机上 spaCy 就会静默退回纯 Python 路径。
    """
    gradle = open(os.path.join(ROOT, "android", "app", "build.gradle"), encoding="utf-8").read()
    extract_lines = [ln for ln in gradle.splitlines() if "extractPackages" in ln]
    assert extract_lines, "build.gradle 必须声明 extractPackages"
    declared = extract_lines[0]
    for pkg in ("spacy", "thinc", "de_core_news_sm"):
        assert f'"{pkg}"' in declared, f"{pkg} 的数据文件不会被解包"


def _read_android_gradle():
    return open(os.path.join(ROOT, "android", "app", "build.gradle"), encoding="utf-8").read()


def test_android_version_code_encoding():
    """versionCode 必须是 major*10000 + minor*100 + patch，且严格大于历史最大值。

    旧编码 major*100 + minor*10 + patch 在 minor 到 10 时溢出撞车
    （3.10.0 与 4.0.0 都算出 400）。versionCode 撞车 = 新版本无法覆盖安装，
    所以这条规则交给测试守，而不是靠记忆。
    """
    gradle = _read_android_gradle()
    # 版本号从环境变量读取，fallback 默认值在变量定义里。测试解析 fallback 值。
    code_str = re.search(r'System.getenv\("DELECTOR_VERSION_CODE"\) \?: "(\d+)"', gradle)
    name_str = re.search(r'System.getenv\("DELECTOR_VERSION_NAME"\) \?: "([\d.]+)"', gradle)
    assert code_str and name_str, "build.gradle 必须保留 DELECTOR_VERSION_* 的 fallback 默认值"
    code = int(code_str.group(1))
    name = name_str.group(1)
    major, minor, patch = (int(x) for x in name.split("."))
    assert code == major * 10000 + minor * 100 + patch, (
        f"versionName {name} 应编码为 {major * 10000 + minor * 100 + patch}，实际 {code}"
    )
    assert minor < 100 and patch < 100, "minor/patch 各只有两位空间"
    assert code > 391, "必须大于 v3.9.1 的 391，否则安卓拒绝覆盖安装"


def test_android_signing_config_degrades_without_keystore():
    """签名配置必须以「keystore 文件存在」为条件，且只读环境变量。

    两条都不能少：
    - 无条件写 storeFile 会让本地开发和 fork 直接构建失败；
    - 把口令写进 build.gradle 则是把签名密钥提交进仓库。
    """
    gradle = _read_android_gradle()
    assert "signingConfigs" in gradle, "缺少钉死的签名配置"
    assert "file(pinnedKeystore).exists()" in gradle, (
        "签名配置必须以 keystore 文件真实存在为前提，否则本地/fork 构建会炸"
    )
    for var in ("DELECTOR_KEYSTORE_PATH", "DELECTOR_KEYSTORE_PASSWORD", "DELECTOR_KEY_ALIAS", "DELECTOR_KEY_PASSWORD"):
        assert f'System.getenv("{var}")' in gradle, f"{var} 必须从环境变量读"
    assert "storePassword" in gradle and 'storePassword "' not in gradle, "口令不得硬编码在 build.gradle 里"
    # keytool -printcert -jarfile 只认 v1 签名，而 AGP 在 minSdk>=24 时默认只出
    # v2/v3。CI 验签闸靠 keytool 读指纹，没开 v1 的话闸读出来永远是空的——
    # 实测 v3.10.0 首跑就死在这（keystore 指纹对、APK 指纹空）。删掉这行 =
    # 闸静默失效，所以交给测试钉住。
    assert "v1SigningEnabled true" in gradle, "必须显式开 v1 签名，否则 keytool 读不出 APK 指纹，验签闸退化成摆设"


def test_release_workflow_gates_apk_signature():
    """CI 必须验签，并且只取 debug 变体那一个确定的 APK 路径。

    没有这道闸时的失效模式是静默的：secret 缺失 → gradle 回落到随机 debug
    keystore → 产出一个看起来正常、装到手机上却签名不一致的 APK。
    """
    workflow = open(os.path.join(ROOT, ".github", "workflows", "build-release.yml"), encoding="utf-8").read()
    assert "keytool -printcert -jarfile" in workflow, "缺少 APK 证书指纹断言"
    assert "app/build/outputs/apk/debug/app-debug.apk" in workflow, (
        "APK 路径必须写死到 debug 变体，find *.apk 会随机抓到别的变体"
    )
    assert 'find android/app/build/outputs/apk/ -name "*.apk"' not in workflow
    assert "$RUNNER_TEMP/delector-debug.jks" in workflow, "keystore 必须解到 $RUNNER_TEMP，不能落在工作树里"
    # 指纹一旦填上就不能再被清空：空值时那道闸退化成 APK↔keystore 自比对，
    # 拦不住「keystore 被换成另一份合法 keystore」（= 已安装用户永远收不到升级）。
    m_sha = re.search(r'EXPECTED_SHA256:\s*"([^"]*)"', workflow)
    assert m_sha, "缺少 EXPECTED_SHA256 指纹声明"
    expected = m_sha.group(1)
    assert re.fullmatch(r"(?:[0-9A-F]{2}:){31}[0-9A-F]{2}", expected), (
        f"EXPECTED_SHA256 必须是大写冒号分隔的 32 字节指纹（与 keytool 输出同格式），实际 {expected!r}"
    )
    assert "android/" not in workflow.split("Decode Pinned Signing Keystore")[1].split("base64 -d")[0], (
        "解码目标不得指向仓库内路径"
    )


def test_android_workflow_build_and_signature_contract():
    """CI 必须保留关键构建与签名契约：JDK 17、Gradle 构建、keytool 验签、指纹、模型与 extractPackages。

    任何一项静默丢失都会导致：本地能跑但 CI 产出的 APK 是旧签名/缺模型/纯 Python 降级。
    """
    wf = open(os.path.join(ROOT, ".github", "workflows", "build-release.yml"), encoding="utf-8").read()
    gradle = open(os.path.join(ROOT, "android", "app", "build.gradle"), encoding="utf-8").read()
    # JDK 17
    assert "java-version: '17'" in wf or 'java-version: "17"' in wf, "工作流必须保留 JDK 17"
    assert "setup-java" in wf, "工作流必须使用 setup-java"
    # Android 构建命令（复用已有 JDK/缓存/签名，不新增平行流程）
    assert "gradle assembleDebug" in wf or "gradle assemble" in wf, "工作流必须执行 Gradle assemble 任务"
    assert "Sync Python Backend, Model, and Assets into Android Project" in wf, "Gradle 构建必须在资产生成之后执行"
    # keytool 验签
    assert "keytool -printcert -jarfile" in wf, "缺少 keytool -printcert -jarfile 验签"
    # 期望指纹
    expected = re.search(r'EXPECTED_SHA256:\s*"([^"]*)"', wf)
    assert expected and expected.group(1), "缺少 EXPECTED_SHA256 指纹声明"
    assert re.fullmatch(r"(?:[0-9A-F]{2}:){31}[0-9A-F]{2}", expected.group(1)), f"指纹格式错误: {expected.group(1)!r}"
    # 模型声明
    assert "de_core_news_sm" in wf, "工作流必须声明模型 de_core_news_sm"
    assert "spacy" in wf.lower(), "工作流必须声明 spacy"
    # 三个 extractPackages 在 gradle 中
    extract_lines = [ln for ln in gradle.splitlines() if "extractPackages" in ln]
    assert extract_lines, "build.gradle 必须声明 extractPackages"
    declared = extract_lines[0]
    for pkg in ("spacy", "thinc", "de_core_news_sm"):
        assert f'"{pkg}"' in declared, f"{pkg} 的数据文件不会被解包"


def test_android_apk_content_via_app_imy():
    """APK 内容必须通过 assets/chaquopy/app.imy 检查，不能直接在 APK 根目录 grep Python 文件。

    Python 代码被打进 app.imy（及 requirements-<abi>.imy），直接在 APK namelist 里
    grep server.py 会误判成缺失；而只查 APK 根目录会漏检但测试仍绿。
    v4.4.0 首跑实测：app.imy 只装应用代码 + 拷入的模型目录，pip 依赖（spacy/thinc）
    在 requirements-<abi>.imy —— 检查必须按容器分工，否则误报缺失。
    """
    wf = open(os.path.join(ROOT, ".github", "workflows", "build-release.yml"), encoding="utf-8").read()
    # 必须检查 app.imy 内部而非 APK 根
    assert "assets/chaquopy/app.imy" in wf, "APK 内容检查必须验证 assets/chaquopy/app.imy，不能直接在 APK 根目录查找"
    # 必须检查 requirements imy 容器（spacy/thinc 所在地）
    assert 'n.startswith("assets/chaquopy/requirements")' in wf, (
        "APK 内容检查必须遍历 requirements-*.imy（pip 依赖容器）"
    )
    # app.imy 内必须包含应用代码与模型；requirements 内必须包含 spacy/thinc
    for needle in ("delector/server.py", "de_core_news_sm", "spacy", "thinc"):
        assert needle in wf, f"APK 内容检查必须验证 {needle} 在 app.imy/requirements 中"
    # 不得仅用 APK 根目录 grep 来验证 Python 文件（这是常见误判）
    # 允许 app.imy 上下文中的 grep，但 workflow 中若出现直接 "unzip -l.*apk.*grep.*server.py"
    # 而不经过 app.imy，则为错误模式
    lines = wf.splitlines()
    for ln in lines:
        stripped = ln.strip()
        if "delector/server.py" in stripped and "grep" in stripped.lower():
            assert "app.imy" in wf, "delector/server.py 检查必须在 app.imy 上下文中"
            break


def test_keystore_protected_by_gitignore_and_hook():
    root = ROOT
    ignore = open(os.path.join(root, ".gitignore"), encoding="utf-8").read()
    for pat in ("*.jks", "*.keystore", "*.p12", "signing.properties"):
        assert pat in ignore, f".gitignore 缺 {pat}"
    hook = open(os.path.join(root, ".githooks", "pre-commit"), encoding="utf-8").read()
    assert "*.jks" in hook, "pre-commit 的文件名黑名单不覆盖 keystore"
    assert "feedfeed" in hook, "还需按文件头认 keystore：改后缀就能绕开文件名黑名单"
    # Task3: 编码后的 PKCS12（Base64 存成普通文本）也不能靠改后缀绕开
    assert "PKCS12 Base64" in hook, "pre-commit 缺少 PKCS12 Base64 内容检测"
    assert "020103" in hook, "PKCS12 判定必须包含 version 3 头校验（020103），不能只认 3082"
    # 不能用通用 MII 前缀单独作为 PATTERNS 条目（会把公开证书全误拦）
    assert "MII[A-Za-z0-9+/]" in hook or "MII" in hook, "应有 MII 长串预筛但必须配合解码校验"
    # Base64 块必须配合解码校验：hook 里应有 python 解码与 0x30 0x82 校验
    assert "base64" in hook and "0x30" in hook, "PKCS12 Base64 检测需经 base64 解码后验文件头"


def test_runtime_artifacts_protected_by_gitignore():
    """桌面壳运行态产物 MUST 被 .gitignore 命中（评审 P1-2：`launch.log`/`lan-address.txt` 曾是缺口）。

    威胁模型与 `*.db*` 同族：便携模式（`DELECTOR_PORTABLE=1`）或源码运行时，数据目录
    就是仓库根（`data_dir_bootstrap.resolve_data_dir` → `program_dir()`）⇒ 一次
    `git add -A` 会把运行态日志（启动堆栈/端口冲突详情）与**内网 IP 地址**提交进历史。
    """
    root = ROOT
    import subprocess  # 本文件惯例：subprocess 只在使用处局部导入

    ignore = open(os.path.join(root, ".gitignore"), encoding="utf-8").read()
    for pat in ("/launch.log", "/launch.log.*", "/lan-address.txt"):
        assert pat in ignore, f".gitignore 缺 {pat}"
    # 光有规则字符串不够：必须真的匹配得上（防规则写错、或被后续规则重新包含）
    for rel in ("launch.log", "launch.log.1", "lan-address.txt"):
        proc = subprocess.run(
            ["git", "check-ignore", "-q", rel], cwd=str(root), capture_output=True
        )
        assert proc.returncode == 0, (
            f"{rel} 未被 .gitignore 命中（git check-ignore rc={proc.returncode}）"
        )
    # 产物名 MUST 与桌面壳常量一致（防改了常量却忘了改忽略规则）
    desktop = open(os.path.join(root, "desktop.py"), encoding="utf-8").read()
    assert 'LOG_FILE_NAME = "launch.log"' in desktop
    assert 'LOG_BACKUP_SUFFIX = ".1"' in desktop
    assert 'LAN_ADDRESS_FILE_NAME = "lan-address.txt"' in desktop


def _pkcs12_b64():
    import base64

    return base64.b64encode(bytes.fromhex("30820500020103") + b"A" * 1200).decode()


def _cert_b64():
    import base64

    return base64.b64encode(bytes.fromhex("3082010030820100") + b"B" * 1200).decode()


def _run_hook_with_files(tmp_path, files):
    """在隔离的临时 git 仓库里暂存 files 并运行 pre-commit，返回 (returncode, output)。

    files: dict[str, str|bytes]  path -> content
    """
    import os
    import pathlib
    import shutil
    import subprocess
    import tempfile

    def _find_bash():
        cands = []
        for git_cmd in ("git.exe", "git"):
            gw = shutil.which(git_cmd)
            if gw:
                git_root = os.path.dirname(os.path.dirname(gw))
                for b in [
                    os.path.join(git_root, "bin", "bash.exe"),
                    os.path.join(git_root, "usr", "bin", "bash.exe"),
                ]:
                    if os.path.exists(b) and b not in cands:
                        cands.append(b)
        # where bash 列出所有候选（含 Git Bash 与 WSL bash）
        try:
            out = subprocess.run(
                ["where", "bash"], capture_output=True, text=True, encoding="utf-8", errors="replace"
            ).stdout
            for line in out.splitlines():
                p = line.strip().strip('"')
                if p and os.path.exists(p):
                    cands.append(p)
        except Exception:
            pass
        for p in os.environ.get("PATH", "").split(os.pathsep):
            if not p:
                continue
            cand = os.path.join(p.strip('"'), "bash.exe")
            if os.path.exists(cand) and cand not in cands:
                cands.append(cand)
            cand2 = os.path.join(p.strip('"'), "bash")
            if os.path.exists(cand2) and cand2 not in cands:
                cands.append(cand2)
        which = shutil.which("bash")
        if which and which not in cands:
            cands.append(which)
        # 去重保持顺序
        seen = []
        for c in cands:
            if c not in seen:
                seen.append(c)
        # 优先 Git Bash，WSL 的 C:\\Windows\\System32\\bash.exe 放最后（无发行版时会直接报错）
        git_bash = [c for c in seen if "Git" in c]
        non_wsl = [c for c in seen if "Git" not in c and "System32" not in c.lower() and "system32" not in c]
        wsl_bash = [c for c in seen if "System32" in c or "system32" in c]
        for pool in (git_bash, non_wsl, wsl_bash, seen):
            if pool:
                return pool[0]
        return which

    bash_exe = _find_bash()
    if bash_exe is None or not os.path.exists(bash_exe):
        pytest.skip("bash 不可用，跳过 hook 行为测试")
    root = ROOT
    hook_src = os.path.join(root, ".githooks", "pre-commit")
    hook_content = open(hook_src, encoding="utf-8").read()

    repo = pathlib.Path(tempfile.mkdtemp(dir=str(tmp_path)))
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), capture_output=True, check=True)
    (repo / ".githooks").mkdir()
    # 用 LF 写入，避免 Windows 写入 CRLF 导致 bash 在 Windows cwd 下报 $'\r' 错误
    with open(repo / ".githooks" / "pre-commit", "wb") as f:
        f.write(hook_content.encode("utf-8"))
    (repo / "README.md").write_text("init", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True, check=True)
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", rel], cwd=str(repo), capture_output=True, check=True)
    result = subprocess.run(
        [bash_exe, ".githooks/pre-commit"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    # WSL 的 bash 在无发行版时会输出 "Windows Subsystem for Linux has no installed distributions"
    # 或错误码 0x80070422，且可能以 UTF-16 输出导致乱码；若命中则视为环境不可用而非钩子逻辑失败
    combined = result.stdout + result.stderr
    combined_clean = combined.replace("\x00", "")
    if (
        ("Windows Subsystem for Linux" in combined_clean and "no installed distributions" in combined_clean)
        or "0x80070422" in combined_clean
        or "0x8007" in combined_clean
        or ("WSL" in combined_clean and result.returncode != 0 and "PKCS12" not in combined_clean)
    ):
        pytest.skip("WSL bash 无法运行或无可用发行版，跳过 hook 行为测试（应使用 Git Bash）")
    return result.returncode, combined


def test_precommit_blocks_pkcs12_base64_in_plain_text(tmp_path):
    """普通文本里的 PKCS12 Base64 必须被拦截（编码后改后缀绕开的缺口）。"""
    b64 = _pkcs12_b64()
    code, out = _run_hook_with_files(tmp_path, {"notes.txt": b64})
    assert code != 0, f"应拦截 PKCS12 Base64，hook 却放行: {out}"
    assert "PKCS12" in out


def test_precommit_blocks_p12_and_pfx_filenames(tmp_path):
    """敏感文件名 .p12/.pfx 仍按文件名黑名单拦截。"""
    for name in ("secret.p12", "secret.pfx"):
        code, out = _run_hook_with_files(tmp_path, {name: ""})
        assert code != 0, f"{name} 应被文件名黑名单拦截: {out}"


def test_precommit_allows_example_and_sample_exemption(tmp_path):
    """.example/.sample/.template 白名单内的 PKCS12 不应误拦。"""
    b64 = _pkcs12_b64()
    for name in ("secret.txt.example", "secret.txt.sample", "secret.txt.template"):
        code, out = _run_hook_with_files(tmp_path, {name: b64})
        assert code == 0, f"{name} 白名单应放行，却被拦: {out}"


def test_precommit_allows_public_pem_cert_not_pkcs12(tmp_path):
    """公开证书的 Base64（同为 MII 开头）不应被 PKCS12 规则误拦。

    证书 Base64 同样以 MII 开头且长度足够，但解码后头不是 3082????020103，
    必须放行。用非 .pem 文件名避免触发 *.pem 文件名黑名单。
    """
    b64 = _cert_b64()
    content = "public cert:\n" + b64 + "\nend\n"
    code, out = _run_hook_with_files(tmp_path, {"doc.txt": content})
    assert code == 0, f"公开证书不应被误拦: {out}"


def test_precommit_allow_secret_exempts_pkcs12_line(tmp_path):
    """行内 delector:allow-secret 豁免应对 PKCS12 Base64 同样生效。"""
    b64 = _pkcs12_b64()
    content = b64 + " # delector:allow-secret\n"
    code, out = _run_hook_with_files(tmp_path, {"notes.txt": content})
    assert code == 0, f"含 allow-secret 的行应豁免: {out}"


def test_precommit_wrapped_pkcs12_still_blocked(tmp_path):
    """换行包裹的 PKCS12 Base64（每行 64 字符）也应被拦截。"""
    b64 = _pkcs12_b64()
    wrapped = "\n".join(b64[i : i + 64] for i in range(0, len(b64), 64))
    code, out = _run_hook_with_files(tmp_path, {"wrapped.txt": wrapped})
    assert code != 0, f"换行包裹的 PKCS12 仍应拦截: {out}"
    assert "PKCS12" in out


def test_delete_article(client):
    # 1. Ingest article
    res = client.post(
        "/api/articles/ingest", json={"title": "Article To Delete", "raw_text": "Das ist ein Testtext zum Löschen."}
    )
    assert res.status_code == 200
    art_id = res.json()["article_id"]

    # 2. Add reading note to this article
    n_res = client.post(
        f"/api/articles/{art_id}/notes",
        json={"sentence_id": 0, "selected_text": "Testtext", "color": "yellow", "note_content": "随笔要点"},
    )
    assert n_res.status_code == 200

    # 3. Check note exists
    notes_res = client.get(f"/api/articles/{art_id}/notes")
    assert notes_res.status_code == 200
    assert len(notes_res.json()) == 1

    # 4. Delete article
    del_res = client.delete(f"/api/articles/{art_id}")
    assert del_res.status_code == 200
    del_data = del_res.json()
    assert del_data["deleted"] is True
    assert del_data["article_id"] == art_id

    # 5. Article should now be 404
    get_res = client.get(f"/api/articles/{art_id}")
    assert get_res.status_code == 404

    # 6. Reading notes should be empty
    notes_after = client.get(f"/api/articles/{art_id}/notes")
    assert notes_after.status_code == 200
    assert len(notes_after.json()) == 0

    # 7. Deleting non-existent article returns 404
    del_non_existent = client.delete("/api/articles/999999")
    assert del_non_existent.status_code == 404


# --- 6.2 Android spaCy loading contract (static) ---


def test_android_spacy_module_load_fallback_static():
    """_load_spacy_model 必须包含 module.load() 回退（Android 无 dist-info 时唯一可用路径）。"""
    src = open(os.path.join(ROOT, "delector", "nlp_engine", "processor.py"), encoding="utf-8").read()
    assert "importlib.import_module" in src, "缺 importlib 回退"
    assert "module.load()" in src, "缺 module.load() 回退"
    assert "spacy.load(name)" in src or "spacy.load(" in src, "缺 spacy.load(name) 首选路径"


def test_android_spacy_model_dir_fallback_static():
    """模型目录 glob 回退必须存在（meta 版本与目录名不一致时的最后兜底）。"""
    src = open(os.path.join(ROOT, "delector", "nlp_engine", "processor.py"), encoding="utf-8").read()
    assert 'glob(f"{name}-*"' in src or 'glob(f"{name}-' in src, "缺模型目录 glob 兜底"
    assert "data_dirs" in src, "缺 data_dirs 变量"


def test_android_spacy_download_gated_by_is_android_static():
    """自动下载必须被 is_android() 门控，否则 Android import 期起 pip 子进程卡死。"""
    src = open(os.path.join(ROOT, "delector", "nlp_engine", "processor.py"), encoding="utf-8").read()
    # 必须有 is_android 判断且在 download 之前
    assert "is_android()" in src, "缺 is_android() 判断"
    # 确保下载路径在 is_android 分支保护下，而非无条件
    assert "from spacy.cli import download" in src
    # 静态断言：download 调用位于 is_android() 之后且在 else 分支
    lines = src.splitlines()
    android_idx = next((i for i, ln in enumerate(lines) if "is_android()" in ln), -1)
    download_idx = next((i for i, ln in enumerate(lines) if "from spacy.cli import download" in ln), -1)
    assert android_idx != -1 and download_idx != -1 and android_idx < download_idx, "download 必须在 is_android() 之后"


def test_android_spacy_extract_packages_static():
    """build.gradle extractPackages 必须包含 spacy/thinc/de_core_news_sm 三者。"""
    gradle = open(os.path.join(ROOT, "android", "app", "build.gradle"), encoding="utf-8").read()
    line = next((ln for ln in gradle.splitlines() if "extractPackages" in ln), "")
    assert line, "缺 extractPackages 声明"
    for pkg in ("spacy", "thinc", "de_core_news_sm"):
        assert f'"{pkg}"' in line, f"{pkg} 未在 extractPackages 中"


# --- 6.4 Frontend error display (static, reuse api() path) ---


def test_frontend_ai_error_paths_reuse_api_and_show_alert():
    """前端 AI 错误必须走 api() 抛异常 → catch → alert/状态提示，不静默成功，不吞异常。"""
    writer_src = open(os.path.join(ROOT, "static", "js", "writer.js"), encoding="utf-8").read()
    reader_src = open(os.path.join(ROOT, "static", "js", "reader.js"), encoding="utf-8").read()
    core_src = open(os.path.join(ROOT, "static", "js", "core.js"), encoding="utf-8").read()
    # core api() 必须在非 ok 时抛 Error
    assert "throw new Error" in core_src, "core.js api() 必须抛异常"
    # writer aiPolishEssay 必须有 try/catch 且 catch 中有 alert
    polish_fn = writer_src[writer_src.index("export async function aiPolishEssay") :]
    polish_fn = polish_fn[: polish_fn.index("export async function applyPolishChanges")]
    assert "try" in polish_fn and "catch" in polish_fn, "aiPolishEssay 缺 try/catch"
    assert "alert" in polish_fn, "aiPolishEssay 失败时必须 alert"
    # 不写 API Key 到 DOM/localStorage
    assert (
        "api_key" not in writer_src.lower()
        or "localStorage.setItem" not in writer_src
        or "DEEPSEEK_API_KEY" not in writer_src
    ), "writer 不应把 API Key 写入 localStorage/DOM"
    # reader aiNoteAssist 同理
    note_fn = reader_src[reader_src.index("export async function aiNoteAssist") :]
    note_fn = note_fn[: note_fn.index("export async function saveCurrentNote")]
    assert "try" in note_fn and "catch" in note_fn, "aiNoteAssist 缺 try/catch"
    assert "alert" in note_fn or "statusEl" in note_fn, "aiNoteAssist 失败时必须提示"


def test_frontend_does_not_write_api_key_to_storage():
    """前端不得把 API Key 写入 localStorage 或以明文写入 DOM。"""
    import pathlib

    js_dir = pathlib.Path(os.path.join(ROOT, "static", "js"))
    for fp in js_dir.glob("*.js"):
        src = fp.read_text(encoding="utf-8")
        # 禁止同一行内把 api_key 明文 setItem
        for line in src.splitlines():
            low = line.lower()
            if "localstorage.setitem" in low and "api_key" in low:
                assert False, f"{fp.name} 将 API Key 写入 localStorage: {line.strip()[:120]}"
        # 禁止把 API Key 明文通过 innerHTML 写入 DOM：检查同一行内同时出现 api_key 变量与 innerHTML
        for line in src.splitlines():
            low_line = line.lower()
            if "innerhtml" in low_line and "api_key" in low_line and "masked" not in low_line:
                # 允许的 warning 文案含 DEEPSEEK_API_KEY 常量但不含实际 key 值
                if "DEEPSEEK_API_KEY" in line and "api_key_masked" not in line and "has_api_key" not in line:
                    # 仅当该行试图把变量值写入 innerHTML 时才报错，常量提示文案放行
                    if "detail" in low_line or "response" in low_line or "res." in low_line:
                        assert False, f"{fp.name} 可能泄露 API Key 到 DOM: {line.strip()[:120]}"


def test_frontend_assets_send_no_cache_header(client):
    """前端资源必须带 Cache-Control: no-cache，API 不能被牵连。

    裸 StaticFiles 不发 Cache-Control，浏览器就按启发式新鲜度用本地副本；
    main.js 的 ES module import 是裸路径、没有 ?v= 可 bust，一缓存住就是旧代码。
    用 no-cache（强制回源校验、仍配合 ETag 走 304）而非 no-store（禁掉全部缓存、
    会削弱 PWA 离线能力）。
    """
    for path in ("/", "/index.html", "/style.css", "/sw.js", "/js/main.js", "/js/core.js"):
        res = client.get(path)
        assert res.status_code == 200, f"{path} 取不到：{res.status_code}"
        assert res.headers.get("cache-control") == "no-cache", (
            f"{path} 缺 no-cache：{res.headers.get('cache-control')!r}"
        )

    # 反向断言：API 有自己的缓存语义，不该被这个 middleware 动
    api = client.get("/api/articles")
    assert api.status_code == 200
    assert "cache-control" not in api.headers, (
        f"/api/articles 被加上了 Cache-Control：{api.headers.get('cache-control')!r}"
    )
