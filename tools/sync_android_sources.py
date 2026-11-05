"""把桌面端 Python 后端、德语模型与静态资源同步进 Android 工程。

Chaquopy 只从 ``android/app/src/main/python`` 收应用代码；该目录与
``android/app/src/main/assets/static`` 都是生成物，被 ``.gitignore`` 忽略。
CI 的两个 Android job 与本地构建都必须先跑本脚本，否则 ``app.imy`` 会是
22 B 的 EOCD-only 空包：APK 能装、Chaquopy 能起，但启动即报
``ModuleNotFoundError: No module named 'start'``。

用法::

    python tools/sync_android_sources.py            # 同步（幂等）
    python tools/sync_android_sources.py --check    # 只检查是否已完整
    python tools/sync_android_sources.py --clean    # 清掉生成目录

模型目录默认从当前解释器导入 ``de_core_news_sm`` 解析；若当前环境没装模型，
用 ``--model-dir`` / ``--model-dist-info`` 显式指定（脚本只依赖标准库）。
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import shutil
import sys
from pathlib import Path

_PYTHON_DEST = Path("app/src/main/python")
_STATIC_DEST = Path("app/src/main/assets/static")
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


class SyncError(RuntimeError):
    """源文件缺失或生成目录不完整。"""


def _fail(message: str) -> int:
    print(f"::error::{message}", file=sys.stderr)
    return 2


def _resolve_model(
    model_dir: str | None, model_dist_info: str | None
) -> tuple[Path, Path]:
    if model_dir:
        model = Path(model_dir).resolve()
        dist_candidates = (
            [Path(model_dist_info).resolve()]
            if model_dist_info
            else sorted(model.parent.glob("de_core_news_sm-*.dist-info"))
        )
        if not dist_candidates:
            raise SyncError(
                "显式指定 --model-dir 时未找到 de_core_news_sm-*.dist-info，"
                "请同时传 --model-dist-info"
            )
        return model, dist_candidates[0]

    spec = importlib.util.find_spec("de_core_news_sm")
    if spec is None or not spec.origin:
        raise SyncError(
            "当前 Python 环境未安装 de_core_news_sm："
            "请用装好模型的解释器（如 .venv），或传 --model-dir/--model-dist-info"
        )
    model = Path(spec.origin).resolve().parent
    hits = sorted(glob.glob(str(model.parent / "de_core_news_sm-*.dist-info")))
    if not hits:
        raise SyncError(
            f"未找到 {model.name} 的 dist-info（与模型目录同级）：{model.parent}"
        )
    return model, Path(hits[0])


def _require_source(path: Path, label: str) -> None:
    if not path.exists():
        raise SyncError(f"缺少{label}：{path}")


def _dest_paths(android_root: Path) -> tuple[Path, Path]:
    return android_root / _PYTHON_DEST, android_root / _STATIC_DEST


def _copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, ignore=_IGNORE)


def _dir_stats(path: Path) -> tuple[int, int]:
    files = [item for item in path.rglob("*") if item.is_file()]
    return len(files), sum(item.stat().st_size for item in files)


def sync(repo_root: Path, android_root: Path, model: Path, dist_info: Path) -> None:
    start_py = repo_root / "start.py"
    delector = repo_root / "delector"
    static = repo_root / "static"

    _require_source(start_py, "桌面入口 start.py")
    _require_source(delector, "业务包 delector/")
    _require_source(static / "index.html", "静态首页 static/index.html")
    _require_source(model, "模型目录 de_core_news_sm/")
    _require_source(dist_info, "模型元数据 dist-info/")

    python_dest, static_dest = _dest_paths(android_root)
    python_dest.parent.mkdir(parents=True, exist_ok=True)
    static_dest.parent.mkdir(parents=True, exist_ok=True)

    # 幂等：先清掉受管目标，再整块复制，避免重复跑出现嵌套副本。
    for managed in (python_dest, static_dest):
        if managed.exists():
            shutil.rmtree(managed)

    python_dest.mkdir(parents=True)
    shutil.copy2(start_py, python_dest / "start.py")
    _copy_tree(delector, python_dest / "delector")
    _copy_tree(model, python_dest / "de_core_news_sm")
    _copy_tree(dist_info, python_dest / dist_info.name)
    _copy_tree(static, static_dest)

    files, size = _dir_stats(python_dest)
    s_files, s_size = _dir_stats(static_dest)
    print(
        f"同步完成：{python_dest}（{files} 文件，{size} B）；"
        f"{static_dest}（{s_files} 文件，{s_size} B）"
    )


def check(android_root: Path) -> None:
    python_dest, static_dest = _dest_paths(android_root)
    missing: list[str] = []

    start = python_dest / "start.py"
    if not start.is_file() or start.stat().st_size == 0:
        missing.append("start.py")

    if not any((python_dest / "delector").glob("**/*.py")):
        missing.append("delector/")

    model = python_dest / "de_core_news_sm"
    if not model.is_dir() or not any(model.rglob("*")):
        missing.append("de_core_news_sm/")

    if not any(python_dest.glob("de_core_news_sm-*.dist-info")):
        missing.append("de_core_news_sm-*.dist-info/")

    index = static_dest / "index.html"
    if not index.is_file() or index.stat().st_size == 0:
        missing.append("assets/static/index.html")

    if missing:
        raise SyncError("Android 源码未同步完整，缺少：" + "、".join(missing))


def clean(android_root: Path) -> None:
    removed: list[str] = []
    for managed in _dest_paths(android_root):
        if managed.exists():
            shutil.rmtree(managed)
            removed.append(str(managed))
    if removed:
        print("已清理：" + "；".join(removed))
    else:
        print("无需清理：生成目录均不存在")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="仓库根目录（默认脚本所在仓库）",
    )
    parser.add_argument(
        "--android-root",
        default=None,
        help="Android 工程目录（默认 <repo-root>/android）",
    )
    parser.add_argument(
        "--model-dir",
        default=None,
        help="显式模型目录；默认从当前解释器导入 de_core_news_sm",
    )
    parser.add_argument(
        "--model-dist-info",
        default=None,
        help="显式模型 dist-info 目录；默认在模型目录同级按 de_core_news_sm-*.dist-info 匹配",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="只检查是否已同步完整")
    mode.add_argument("--clean", action="store_true", help="清掉生成目录")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    android_root = (
        Path(args.android_root).resolve()
        if args.android_root
        else repo_root / "android"
    )

    try:
        if args.check:
            check(android_root)
            print("检查通过：Android 源码已同步")
            return 0
        if args.clean:
            clean(android_root)
            return 0
        model, dist_info = _resolve_model(args.model_dir, args.model_dist_info)
        sync(repo_root, android_root, model, dist_info)
        return 0
    except SyncError as exc:
        return _fail(str(exc))
    except OSError as exc:
        return _fail(f"文件操作失败：{exc}")


if __name__ == "__main__":
    raise SystemExit(main())
