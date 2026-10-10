# -*- coding: utf-8 -*-
r"""start.py 启动横幅在"敌意流"（重定向 + locale 编码）下不得崩（RED → GREEN 回归锁）。

事故（CI 新闸抓到，是产品真 bug 不是闸的错）
-------------------------------------------
Windows 冒烟 job 真启产物时 `DeLector.exe --server-only` **一启动就崩**：退出码 1，服务日志尾部：

    UnicodeEncodeError: 'charmap' codec can't encode characters in position 13-28: ...

根因：`start.py` 的启动横幅用 `print()` 打中文，而子进程 stdout 被**重定向到文件**时，流按
locale/ANSI 编码打开（CI runner 上是 cp1252，本机 GBK），且 **stdout 的 errors 是 `strict`** ⇒
打不出中文即抛 `UnicodeEncodeError` ⇒ 进程退出 1。**含义**：这个应用在"输出被重定向 / 被日志
采集 / 由服务或计划任务拉起"的环境里根本起不来 —— 恰是"当服务用"最常见的环境。

为什么只有 stdout 会崩（顺带钉住的边界）
---------------------------------------
实测（本机 Python 3.11）：`PYTHONIOENCODING=cp1252` 下 `sys.stdout.errors == "strict"` 会抛，
但 `sys.stderr.errors == "backslashreplace"` **不抛**（转成 `\uXXXX` 转义照常输出）。故横幅这类走
**stdout** 的中文才会崩；`desktop.py` 的中文警告全部走 stderr，本就安全 —— 这也是本组用例只锁
stdout 横幅、不扩到 desktop.py 的原因。

为什么用真子进程（而非把 sys.stdout 换成 cp1252 包装对象再调函数）
-----------------------------------------------------------------
修法落在 `start.py` 的**模块顶层**（与 package_windows.py 顶部同款：把流 reconfigure 成 utf-8）。
该语句在 `import start` 时对**当时**的 `sys.stdout` 生效；若在测试进程里先 import 再把 `sys.stdout`
换成一个 cp1252 包装对象，测的其实是"测试自己换的流"，**去掉修复也不会红**（假绿）。故本用例用
**真子进程**：`PYTHONIOENCODING=cp1252` + stdout 重定向到文件，忠实复现"敌意流"，断言退出码 0
且无 `UnicodeEncodeError`。

纪律
----
* MUST 把 `DELECTOR_DATA_DIR` 钉进 tmp（bootstrap 纪律：不钉会按平台默认落点、可能搬真实库）。
* 断言"真打出了中文文案"，防恒真 —— 不是只查源码里有没有 reconfigure 字样。
* 变异自证：去掉 start.py 顶部的 reconfigure ⇒ 本用例转红（原始报错 position 13-28 复现）；恢复 ⇒ 绿。
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 复现 CI 故障的编码：cp1252 编不出这些中文（CI 报的 position 13-28 正是横幅标题行的汉字）。
HOSTILE_ENCODING = "cp1252"


def test_start_banner_survives_redirected_cp1252_stdout(tmp_path: Path) -> None:
    """start.py 的启动横幅：在被重定向、cp1252 的 stdout 上打中文必须不抛、退出 0。"""
    log_path = tmp_path / "output.log"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = HOSTILE_ENCODING
    # 钉数据落点，隔离副作用（绝不碰真实库）。本用例只 import start + 调 banner，不触发 bootstrap。
    env["DELECTOR_DATA_DIR"] = str(tmp_path / "data")
    env.pop("PYTHONUTF8", None)  # 别让 UTF-8 模式掩盖：要的正是"非 utf-8 的敌意流"

    # android=True：走"仅本机监听"分支，避开 get_local_ip 的网络调用，让用例确定、快。
    script = "import start; start.print_banner(8000, True)"
    with open(log_path, "wb") as handle:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(REPO_ROOT),
            stdout=handle,
            stderr=subprocess.STDOUT,
            env=env,
            timeout=120,
        )

    output = log_path.read_bytes().decode("utf-8", errors="replace")

    assert proc.returncode == 0, f"脚本在敌意流下非零退出（退出码 {proc.returncode}）：\n{output}"
    assert "UnicodeEncodeError" not in output, f"横幅仍抛 UnicodeEncodeError：\n{output}"
    # 防恒真：横幅必须真的打出来了（去掉顶部的 reconfigure，这里连同退出码一起红）。
    assert "DeLector" in output and "德语" in output, f"横幅未按预期打印：\n{output!r}"
