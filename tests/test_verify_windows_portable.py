# -*- coding: utf-8 -*-
"""`tools/verify_windows_portable.py` 纯逻辑单元测试（**不真跑 exe**）。

覆盖范围（只测不依赖 Windows / 不启动产物的纯函数）
--------------------------------------------------
产物目录定位（唯一 / 多候选 / 无候选 / override）、`.build-info.json` 四键与 commit 抗陈旧
一致性、`.env` 检出、WebView2 DLL 缺失检出、`_internal` 关键目录缺失检出、健康就绪判定。

为什么单测**刻意不跑 exe**：真启段（launch / terminate / 端口 / 孤儿）要起真进程、绑真端口，
既慢又绑死平台，还会在无桌面会话的 runner 上产生与环境耦合的假红 —— 那一段由 CI 的 Windows
冒烟 job 与 `build-release.yml` 的验包步用**真实产物**跑（见 `.github/workflows/`）。

断言纪律（防恒真）
------------------
每条断言都必须能被"改坏实现"打红，禁止"字符串在场 / 不抛异常即过"这类恒真断言。
末尾 MUTATION 表逐条给出"改坏实现哪一处 ⇒ 哪条用例转红"的对照，供变异自证核对。
"""

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_UNDER_TEST = _REPO_ROOT / "tools" / "verify_windows_portable.py"


def _load_under_test() -> Any:
    """按路径加载被守卫脚本（`tools/` 不是 package，不能 `import`）。"""
    spec = importlib.util.spec_from_file_location("verify_windows_portable_under_test", _UNDER_TEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vp = _load_under_test()


def _make_artifact(tmp_path: Path, name: str = "DeLector-v9.9.9-Windows-x64-Portable") -> Path:
    """造一个空的假产物目录（单测只关心纯函数读到的文件树，不需要真 exe）。"""
    artifact = tmp_path / name
    artifact.mkdir(parents=True, exist_ok=True)
    return artifact


# ── (a) 产物定位 ─────────────────────────────────────────────────────────────
def test_locate_artifact_override_wins(tmp_path: Path) -> None:
    """显式 override 优先，即使 dist 下还有别的候选。"""
    _make_artifact(tmp_path, "DeLector-v1-Windows-x64-Portable")
    override = _make_artifact(tmp_path, "manual-dir")
    assert vp.locate_artifact(tmp_path, str(override)) == override


def test_locate_artifact_unique_match(tmp_path: Path) -> None:
    """dist 下唯一候选时按 glob 命中。"""
    artifact = _make_artifact(tmp_path)
    assert vp.locate_artifact(tmp_path) == artifact


def test_locate_artifact_no_match_raises(tmp_path: Path) -> None:
    """无候选必须抛错（**不猜**），且报错带上期望的 glob 口径。"""
    with pytest.raises(vp.VerifyError) as excinfo:
        vp.locate_artifact(tmp_path)
    assert vp.ARTIFACT_GLOB in str(excinfo.value)


def test_locate_artifact_multiple_matches_raises(tmp_path: Path) -> None:
    """多候选必须抛错并提示用 --artifact 指定（猜错产物 = 验收错的东西）。"""
    _make_artifact(tmp_path, "DeLector-v1-Windows-x64-Portable")
    _make_artifact(tmp_path, "DeLector-v2-Windows-x64-Portable")
    with pytest.raises(vp.VerifyError) as excinfo:
        vp.locate_artifact(tmp_path)
    assert "--artifact" in str(excinfo.value)


def test_locate_artifact_override_missing_raises(tmp_path: Path) -> None:
    """override 指向不存在的目录必须抛错。"""
    with pytest.raises(vp.VerifyError):
        vp.locate_artifact(tmp_path, str(tmp_path / "does-not-exist"))


# ── (a) .build-info.json 读取与四键 ───────────────────────────────────────────
def test_read_build_info_missing_file_raises(tmp_path: Path) -> None:
    artifact = _make_artifact(tmp_path)
    with pytest.raises(vp.VerifyError):
        vp.read_build_info(artifact)


def test_read_build_info_non_object_raises(tmp_path: Path) -> None:
    """顶层不是 JSON 对象（数组）必须抛错，不能当成合法指纹。"""
    artifact = _make_artifact(tmp_path)
    (artifact / vp.BUILD_INFO_FILENAME).write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(vp.VerifyError):
        vp.read_build_info(artifact)


def test_read_build_info_roundtrip(tmp_path: Path) -> None:
    artifact = _make_artifact(tmp_path)
    payload = {"commit": "abcdef0", "built_at": "2026-10-10T00:00:00", "app_version": "v9.9.9", "entry": "desktop.py"}
    (artifact / vp.BUILD_INFO_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
    assert vp.read_build_info(artifact) == payload


def test_missing_build_info_keys_reports_blank_or_absent() -> None:
    """缺键与空值都算缺失（空串 / None 不得蒙混成"齐全"）。"""
    info = {"commit": "abcdef0", "built_at": "", "app_version": "v9.9.9", "entry": None}
    assert vp.missing_build_info_keys(info) == ["built_at", "entry"]


def test_missing_build_info_keys_empty_when_complete() -> None:
    info = {key: "x" for key in vp.REQUIRED_BUILD_INFO_KEYS}
    assert vp.missing_build_info_keys(info) == []


def test_missing_build_info_keys_reports_all_when_empty_dict() -> None:
    assert vp.missing_build_info_keys({}) == list(vp.REQUIRED_BUILD_INFO_KEYS)


# ── (a) commit 抗陈旧一致性 ──────────────────────────────────────────────────
def test_commit_mismatch_skipped_without_expectation() -> None:
    """未传期望（含纯空白）⇒ 返回 None（跳过语义，本地默认不拦）。"""
    assert vp.commit_mismatch("abcdef0", "") is None
    assert vp.commit_mismatch("abcdef0", "   ") is None


def test_commit_mismatch_identical_ok() -> None:
    assert vp.commit_mismatch("abcdef0", "abcdef0") is None


def test_commit_mismatch_prefix_ok_both_directions() -> None:
    """短 sha（产物指纹）与长 sha（GITHUB_SHA）互为前缀都算一致。"""
    short = "abcdef0"  # 7 位，达 MIN_COMMIT_LEN
    long = "abcdef0123456789abcdef"
    assert vp.commit_mismatch(short, long) is None
    assert vp.commit_mismatch(long, short) is None


def test_commit_mismatch_is_case_insensitive() -> None:
    assert vp.commit_mismatch("ABCDEF0", "abcdef0") is None


def test_commit_mismatch_different_fails() -> None:
    """真正不一致必须判失败（"以为拿到新包其实是旧包"的防复发闸）。"""
    problem = vp.commit_mismatch("abcdef0", "1234567")
    assert problem is not None
    assert "不一致" in problem


def test_commit_mismatch_coincidental_short_prefix_fails() -> None:
    """短于 MIN_COMMIT_LEN 的前缀不算一致（防 "abc" vs "abcd" 巧合命中）。"""
    assert vp.commit_mismatch("abc", "abcd") is not None


# ── (a) .env 检出 ────────────────────────────────────────────────────────────
def test_find_env_files_detects_variants_recursively(tmp_path: Path) -> None:
    """裸 `.env` 与 `*.env` 变体都要命中，且递归进子目录。"""
    artifact = _make_artifact(tmp_path)
    (artifact / ".env").write_text("K=1", encoding="utf-8")
    (artifact / "prod.env").write_text("K=1", encoding="utf-8")
    (artifact / "readme.txt").write_text("x", encoding="utf-8")
    nested = artifact / "sub"
    nested.mkdir()
    (nested / "nested.env").write_text("K=1", encoding="utf-8")
    hits = sorted(Path(hit).as_posix() for hit in vp.find_env_files(artifact))
    assert hits == [".env", "prod.env", "sub/nested.env"]


def test_find_env_files_clean_when_absent(tmp_path: Path) -> None:
    artifact = _make_artifact(tmp_path)
    (artifact / "application.config").write_text("x", encoding="utf-8")
    assert vp.find_env_files(artifact) == []


# ── (a) WebView2 DLL 缺失检出 ────────────────────────────────────────────────
def test_missing_dlls_all_present_ok(tmp_path: Path) -> None:
    artifact = _make_artifact(tmp_path)
    lib = artifact / "_internal" / "webview" / "lib"
    lib.mkdir(parents=True)
    (lib / "WebView2Loader.dll").write_text("", encoding="utf-8")
    (lib / "Microsoft.Web.WebView2.Core.dll").write_text("", encoding="utf-8")
    assert vp.missing_dlls(artifact) == []


def test_missing_dlls_reports_absent(tmp_path: Path) -> None:
    artifact = _make_artifact(tmp_path)
    assert vp.missing_dlls(artifact) == list(vp.REQUIRED_DLL_NEEDLES)


def test_missing_dlls_ignores_non_dll_namesake(tmp_path: Path) -> None:
    """同名 `.xml`（非 `.dll`）不得算通过：判据锚定 `.dll` 后缀，防白屏包假绿。"""
    artifact = _make_artifact(tmp_path)
    (artifact / "WebView2Loader.xml").write_text("", encoding="utf-8")
    (artifact / "Microsoft.Web.WebView2.Core.xml").write_text("", encoding="utf-8")
    assert vp.missing_dlls(artifact) == list(vp.REQUIRED_DLL_NEEDLES)


# ── (a) _internal 关键目录 ───────────────────────────────────────────────────
def test_missing_internal_dirs_reports_absent(tmp_path: Path) -> None:
    artifact = _make_artifact(tmp_path)
    assert vp.missing_internal_dirs(artifact) == list(vp.REQUIRED_INTERNAL_DIRS)


def test_missing_internal_dirs_all_present_ok(tmp_path: Path) -> None:
    artifact = _make_artifact(tmp_path)
    for name in vp.REQUIRED_INTERNAL_DIRS:
        (artifact / "_internal" / name).mkdir(parents=True)
    assert vp.missing_internal_dirs(artifact) == []


# ── (b) 健康就绪判定（身份校验是硬要求）──────────────────────────────────────
def test_health_is_ready_true_when_identity_and_status_ok() -> None:
    assert vp.health_is_ready(200, {"app": "delector", "status": "ok"}) is True


def test_health_is_ready_false_when_app_is_not_delector() -> None:
    """身份不对必须判否：端口上可能是别的程序 / 旧进程，只判"能连上"会全放行。"""
    assert vp.health_is_ready(200, {"app": "some-other-app", "status": "ok"}) is False


def test_health_is_ready_false_when_identity_field_absent() -> None:
    assert vp.health_is_ready(200, {"status": "ok"}) is False


def test_health_is_ready_false_when_status_not_ok() -> None:
    assert vp.health_is_ready(200, {"app": "delector", "status": "degraded"}) is False


def test_health_is_ready_false_when_not_200() -> None:
    assert vp.health_is_ready(503, {"app": "delector", "status": "ok"}) is False


def test_health_is_ready_false_when_payload_not_object() -> None:
    assert vp.health_is_ready(200, ["ok"]) is False
    assert vp.health_is_ready(200, None) is False


# ── MUTATION 表（防恒真自证：改坏实现 ⇒ 对应用例转红）─────────────────────────
# | 改坏实现（verify_windows_portable.py）                     | 转红的用例                                    |
# |------------------------------------------------------------|-----------------------------------------------|
# | locate_artifact: 多候选时 `return matches[0]`（去抛错）      | test_locate_artifact_multiple_matches_raises  |
# | locate_artifact: 无候选时返回 None 而非抛错                  | test_locate_artifact_no_match_raises          |
# | read_build_info: 去掉 `isinstance(data, dict)` 检查          | test_read_build_info_non_object_raises        |
# | missing_build_info_keys: 只看键是否存在（`in info`）         | test_missing_build_info_keys_reports_blank... |
# | commit_mismatch: 去掉前缀比对（只 `==`）                     | test_commit_mismatch_prefix_ok_both_directions|
# | commit_mismatch: 无条件返回 None                             | test_commit_mismatch_different_fails          |
# | commit_mismatch: 忽略 MIN_COMMIT_LEN（任意前缀都算一致）     | test_commit_mismatch_coincidental_short...    |
# | find_env_files: 只在顶层找（不去递归 rglob）                 | test_find_env_files_detects_variants_recurs.. |
# | missing_dlls: 去掉 `.dll` 后缀锚定（纯子串匹配）             | test_missing_dlls_ignores_non_dll_namesake    |
# | health_is_ready: 去掉 app 身份校验                           | test_health_is_ready_false_when_app_is_not... |
# | health_is_ready: 去掉 status 校验                            | test_health_is_ready_false_when_status...     |
# | health_is_ready: 去掉 `status_code != 200` 判断              | test_health_is_ready_false_when_not_200       |
