#!/usr/bin/env python3
"""P0 视觉回归一键编排：临时数据目录 → 种子卡片 → 启动服务 → 截图矩阵 + 基线导出 → 三条闸。

默认产物落在 `_artifacts/visual-matrix/<时间戳>/`（不入库）：
- `*.png`：12 界面 × 3 宽度的截图
- `computed-style.json`：12 个关键控件的 computed-style 当前值
- `summary.json`：张数、耗时、失败/跳过明细
- `server.log`：本次服务日志（排障用）

用法：
    python tools/visual_matrix.py
    python tools/visual_matrix.py --out _artifacts/my-run --only home,reader --widths 393,1280
    python tools/visual_matrix.py --update-baseline   # 有意变更后更新入库基线
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_ROOT = REPO_ROOT / "tools"
sys.path.insert(0, str(TOOLS_ROOT))

import visual_baseline  # noqa: E402
import visual_gates  # noqa: E402

DEFAULT_WIDTHS = "393,360,1280"
SEED_CARDS = [
    ("Kaffee", "Kaffee", "der", "咖啡", "Jeden Morgen trinke ich einen Kaffee."),
    ("Brötchen", "Brötchen", "das", "小面包", "Ich esse ein Brötchen zum Frühstück."),
    ("Sprachschule", "Sprachschule", "die", "语言学校", "Ich lerne Deutsch an einer Sprachschule."),
    ("Supermarkt", "Supermarkt", "der", "超市", "Am Nachmittag gehe ich in den Supermarkt."),
    ("Wochenende", "Wochenende", "das", "周末", "Letztes Wochenende bin ich nach München gefahren."),
    ("Umweltschutz", "Umweltschutz", "der", "环境保护", "Viele Menschen leisten einen Beitrag zum Umweltschutz."),
]


def _free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex(("127.0.0.1", preferred)) != 0:
            return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _request_json(url: str, method: str = "GET", payload: dict | None = None) -> object:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else None


def _wait_health(base_url: str, process: subprocess.Popen, log_path: Path, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
            raise SystemExit(f"服务启动即退出（exit={process.returncode}）：\n{tail}")
        try:
            _request_json(f"{base_url}/api/health")
            return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.3)
    tail = log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
    raise SystemExit(f"服务在 {timeout:.0f}s 内未就绪：\n{tail}")


def _seed(base_url: str) -> None:
    articles = _request_json(f"{base_url}/api/articles")
    if not isinstance(articles, list) or not articles:
        raise SystemExit("预置文章没有落库：无法打开阅读器")
    for word, lemma, gender, definition, sentence in SEED_CARDS:
        _request_json(
            f"{base_url}/api/cards/vocab",
            method="POST",
            payload={
                "word": word,
                "lemma": lemma,
                "gender": gender,
                "cefr_level": "A1",
                "definition_zh": definition,
                "sentence_context": sentence,
            },
        )


def _start_server(data_dir: Path, port: int, log_path: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["DELECTOR_DATA_DIR"] = str(data_dir)
    # 矩阵只读预置 processed_json，不需要 spaCy 预热；关掉可显著缩短启动时间。
    env["DELECTOR_MODEL_PREWARM"] = "0"
    log_file = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "delector.server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    process._visual_log_handle = log_file  # type: ignore[attr-defined]
    return process


def _stop_server(process: subprocess.Popen) -> None:
    handle = getattr(process, "_visual_log_handle", None)
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    if handle is not None:
        handle.close()


def _print_gate_report(report: dict) -> None:
    visual_gates._print_report(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DeLector P0 视觉回归一键编排")
    parser.add_argument("--out", type=Path, default=None, help="截图与导出目录（默认 _artifacts/visual-matrix/<时间戳>）")
    parser.add_argument("--widths", default=DEFAULT_WIDTHS, help="逗号分隔宽度，默认 393,360,1280")
    parser.add_argument("--only", default=None, help="只跑指定场景 key（逗号分隔）")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=None, help="复用指定数据目录（默认每次新建临时目录）")
    parser.add_argument("--keep-data", action="store_true", help="保留临时数据目录（排障用）")
    parser.add_argument("--update-baseline", action="store_true", help="把本次导出写回入库基线")
    parser.add_argument("--skip-gates", action="store_true", help="只跑矩阵，不跑三条闸")
    args = parser.parse_args(argv)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = args.out or (REPO_ROOT / "_artifacts" / "visual-matrix" / timestamp)
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    computed_path = out_dir / "computed-style.json"
    log_path = out_dir / "server.log"

    temp_data = None
    if args.data_dir:
        data_dir = args.data_dir.resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
    else:
        temp_data = Path(tempfile.mkdtemp(prefix="delector-visual-data-"))
        data_dir = temp_data

    port = _free_port(args.port)
    base_url = f"http://127.0.0.1:{port}"
    process = None
    started = time.monotonic()
    try:
        process = _start_server(data_dir, port, log_path)
        _wait_health(base_url, process, log_path)
        _seed(base_url)
        print(f"服务就绪：{base_url}（数据目录 {data_dir}）")

        command = [
            "node",
            str(TOOLS_ROOT / "visual_matrix.mjs"),
            "--url",
            base_url,
            "--out",
            str(out_dir),
            "--computed-style-out",
            str(computed_path),
            "--widths",
            args.widths,
        ]
        if args.only:
            command.extend(["--only", args.only])
        run = subprocess.run(command, cwd=str(REPO_ROOT), check=False)
        if run.returncode != 0:
            print("矩阵脚本返回非 0；仍继续闸门与基线比对以便一次看清问题", file=sys.stderr)

        gate_report = None
        if not args.skip_gates:
            gate_report = visual_gates.evaluate()
            print()
            _print_gate_report(gate_report)

        baseline_ok = True
        if computed_path.exists() and not args.update_baseline:
            baseline = visual_baseline.load_json(visual_baseline.DEFAULT_BASELINE)
            current = visual_baseline.load_json(computed_path)
            diffs, missing, added = visual_baseline.compare(baseline, current)
            print()
            if diffs or missing or added:
                baseline_ok = False
                for line in diffs:
                    print(f"[DIFF] {line}")
                for line in missing:
                    print(f"[MISSING] {line}")
                for line in added:
                    print(f"[EXTRA] {line}")
                print("computed-style 与基线不一致；确认截图后可用 --update-baseline 更新。")
            else:
                print(f"computed-style 基线一致（{len(baseline['controls'])} 个控件）")
        elif args.update_baseline and computed_path.exists():
            visual_baseline.update(
                visual_baseline.DEFAULT_BASELINE, visual_baseline.load_json(computed_path)
            )
            print(f"已更新基线：{visual_baseline.DEFAULT_BASELINE}")

        summary_path = out_dir / "summary.json"
        summary = {}
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        duration = time.monotonic() - started
        failures = summary.get("failures", [])
        missing_controls = summary.get("missingControls", [])
        print()
        print(
            f"完成：截图 {summary.get('screenshotCount', 0)}/{summary.get('expectedScreenshotCount', 0)} 张，"
            f"总耗时 {duration:.1f}s，失败 {len(failures)}，控件缺失 {len(missing_controls)}"
        )
        for failure in failures:
            print(f"  [FAIL] {failure['scenario']} @ {failure['width']}px：{failure['error']}")
        for missing in missing_controls:
            print(f"  [MISSING] {missing['key']}：{missing['error']}")
        print(f"产物目录：{out_dir}")

        matrix_ok = run.returncode == 0 and not failures and not missing_controls
        gates_ok = gate_report is None or gate_report["ok"]
        return 0 if matrix_ok and baseline_ok and gates_ok else 1
    finally:
        if process is not None:
            _stop_server(process)
        if temp_data is not None and not args.keep_data:
            shutil.rmtree(temp_data, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
