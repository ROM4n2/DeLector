# -*- coding: utf-8 -*-
"""`tools/install_apk.py` 的判据：确认按钮定位必须真能区分「继续安装」与「拒绝」。

背景：2026-11-13 arm64 真机点检时，MIUI 的 `AdbInstallActivity` 确认页 12 秒无人
点击就超时，`adb install` 报 ``INSTALL_FAILED_USER_RESTRICTED: Install canceled by
user``。把定位逻辑抽成纯函数后，可以在无设备环境用真实 dump 片段做阳性/阴性/变异自证。

**只测纯函数**，不跑 `adb`（CI/本机没有真机）。
"""

import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "install_apk_helper", ROOT / "tools" / "install_apk.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 真实 dump 片段（2026-11-13 Redmi Note 8 / MIUI 12 / Android 11，仅保留关键节点）
REAL_DUMP = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
    '<hierarchy rotation="0">\n'
    '  <node text="USB安装提示" class="android.widget.TextView" bounds="[391,1423][688,1491]" />\n'
    '  <node text="org.delector.app" class="android.widget.TextView" bounds="[388,1670][692,1722]" />\n'
    '  <node text="正在通过USB安装此应用，是否继续?" class="android.widget.TextView"'
    ' bounds="[137,1744][960,1796]" />\n'
    '  <node text="拒绝后下次安装不再提示" class="android.widget.CheckBox"'
    ' bounds="[120,1840][960,1910]" />\n'
    '  <node text="继续安装" class="android.widget.Button" bounds="[80,1990][520,2130]" />\n'
    '  <node text="拒绝(7)" class="android.widget.Button" bounds="[559,1990][1000,2130]" />\n'
    "</hierarchy>\n"
)


def test_confirm_button_from_real_miui_dump() -> None:
    """阳性：真实 MIUI 弹窗里「继续安装」的中心点。"""
    module = _load_module()
    assert module.parse_confirm_button(REAL_DUMP) == ((80 + 520) // 2, (1990 + 2130) // 2)


def test_deny_button_is_never_selected() -> None:
    """阴性：只剩「拒绝(7)」时不能返回坐标（点错就是替用户拒绝安装）。"""
    module = _load_module()
    only_deny = REAL_DUMP.replace('text="继续安装"', 'text=""')
    assert module.parse_confirm_button(only_deny) is None


def test_unlaid_out_button_is_skipped() -> None:
    """阴性：`bounds="[0,0][0,0]"` 是未布局节点，点它等于点屏幕左上角。"""
    module = _load_module()
    unlaid = REAL_DUMP.replace("[80,1990][520,2130]", "[0,0][0,0]")
    assert module.parse_confirm_button(unlaid) is None


def test_mutation_without_bounds_is_detected() -> None:
    """变异自证：抹掉 bounds 属性后定位必然失效（证明判据不是靠文本巧合命中）。"""
    module = _load_module()
    import re

    stripped = re.sub(r'\s*bounds="\[[^\]]*\]\[[^\]]*\]"', "", REAL_DUMP)
    assert "bounds=" not in stripped
    assert module.parse_confirm_button(stripped) is None


def test_empty_dump_is_none() -> None:
    """阴性：拿不到 dump（空串）时不得抛异常。"""
    module = _load_module()
    assert module.parse_confirm_button("") is None
