# -*- coding: utf-8 -*-
"""润色循环的**任务级工具白名单**与**前置钩子**（Task 5 · ADR-0023 §8.1 Q4-A / §8.2 第 5 条）。

## 为什么是这三个（D4：只读且相关）

白名单 = `writing_check` / `analyze` / `vocab_stats`，**恰好三项**，取值就是
`delector.tools.<mod>.run` 的**真身**，**同进程直调、不经 HTTP**（D5）。三者都与
「模型取证」直接相关；其中 `analyze` 的只读性有明确运行时前提：

- `writing_check`：转 `services.writing.analyze_a1_email(text, leitpunkte)`
  （`delector/tools/writing_check.py:14`）。A1 硬规则的**确定性裁决**（称呼语/逗号/
  结语），正是循环的收敛判据。**只读**：纯函数，读 payload，不写盘不出网。
- `analyze`：转 `nlp_engine.processor.process_german_text(text)`
  （`delector/tools/analyze.py:9`）。分词/词性/句法统计 ⇒ 模型据此判断句子是否过难、
  用词是否越级。**有条件只读**：仅在本运行时已有可加载模型时成立。桌面端候选模型
  全部失败会执行 `spacy.cli.download(AUTO_DOWNLOAD_MODEL)`，既出网又启动 pip 子进程
  （`processor.py:95-114`）；Android 在 `processor.py:192-198` 显式不下载、降级纯
  Python；Windows 打包产物通过 `--hidden-import` / `--collect-all=de_core_news_sm`
  内置模型。仍保留它，是因为交付产物内置模型，且本机/CI 已安装模型；对应测试会封死
  下载入口并验证该前提，前提失效即判红。
- `vocab_stats`：按 A1∪A2 考纲词集统计覆盖率（`delector/tools/vocab_stats.py:68`）。
  给「这个词超纲吗」一个确定性答案，避免模型凭感觉换词。**只读**：纯函数统计，
  模块级惰性缓存，无 DB 无写。

## 为什么排除 `ingest` / `export` / `tts`（Phase 1 实测，非引述）

- `ingest`（`delector/tools/ingest.py:13` → `fetch_remote_html(url)`）：**出网**。
  把「模型在循环里随手抓一个 URL」变成可达攻击面，且与润色毫无关系。
- `export`（`delector/tools/export.py:14` → 写 `output_path`）：**写盘**。
  循环**每轮都可能调用**，写盘会让「一次润色请求」产生不可控的持久副作用。
- `tts`（`delector/tools/tts_tool.py:10-19` → `services.tts.synthesize`）：**出网**
  （Edge TTS over WSS）+ 算力/内存开销，且与润色任务无关。它把服务返回的音频 bytes
  编码成 base64 直接返回，并不写文件；但放进最多 3 轮的循环仍会成为资源放大器。

一句话：**润色只需要「看」，不需要「拿进来 / 写出去 / 念出来」**。差集守卫由
`tests/test_polish_tools.py` 从 `delector.tools.TOOL_REGISTRY` **现读**钉住（不许抄
一份名字列表）—— 往白名单里加回这三个中的任何一个，那条测试立刻红。

## 鉴权闸 ≠ 能力白名单

`POLISH_TOOL_ALLOWLIST` 回答「模型**能**调什么」（能力面，静态三项）；
`hooks` 回答「**这次**调用谁发起、允不允许」（调用面，每次可不同）。两者正交：
钩子是**前置**的（在任何工具被执行之前串行跑完），抛异常 ⇒ **该次调用被拒**，
拒绝原因作为**返回值**回给调用方 —— 与 Task 4 的 errors-as-messages 一致，
**绝不让异常冒进循环**（否则一次权限抖动就变成 500）。

## 三角一致性规范（ADR-0024 §6）

1. **终审与回灌权威源**：统一收口至 `judge_fn` 与 `violations_of`（带文本族分流）；
2. **模型自查工具 `writing_check`**：复用 `analyze_a1_email`，当存在已加载的 nlp 时自动提供一致的语法检查；
   若未加载则以 `rules_only` 运行并带 `[快速模式: 不含深层语法规则]` 标记，引导模型以回灌裁判反馈为准。

## 刻意不做

- **不吞工具自身的异常**：`fn(payload)` 抛了就原样冒泡。理由：调用方
  `polish_loop.run_polish_loop` 已有「工具失败 ⇒ 作为证据喂回模型」的宽捕；在本模块
  再吞一层，会把「工具坏了」和「权限拒绝」混成同一条消息，掩盖真实原因；
- **不提供 `POLISH_TOOL_ALLOWLIST` 的运行时改写口**：它是 `MappingProxyType`
  （只读视图），任务级差异靠传不同的 `hooks`，不靠改全局表；
- **不新增依赖、不引入任何 agent 框架**（ADR-0001 §1）。
"""

from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping, Sequence

from delector.tools import analyze, vocab_stats, writing_check

# 前置钩子：调用**之前**执行，拿到 `(工具名, payload 快照)`；抛异常 ⇒ 该次调用被拒。
# 返回 `None` 是刻意的：钩子靠**抛**来表达否决；每次传入 `dict(payload)` 快照，
# 钩子的顶层原地改写不会触及后续钩子或最终工具拿到的被审对象。
Hook = Callable[[str, dict[str, Any]], None]

# 显式标注值类型：三个 `run` 的返回注解并不一致（`Any` / `Dict[str, Any]`），
# 靠 mypy 自己 join 会退化成 `object`，显式标出来才能钉住契约。
_TOOLS: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    "writing_check": writing_check.run,
    "analyze": analyze.run,
    "vocab_stats": vocab_stats.run,
}

#: 任务级最小白名单（**恰好 3 项**，只读视图；值 = `delector.tools.<mod>.run` 真身）。
POLISH_TOOL_ALLOWLIST: Mapping[str, Callable[..., Awaitable[dict[str, Any]]]] = MappingProxyType(_TOOLS)


def _brief(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _hook_name(hook: Hook) -> str:
    """钩子的可读名字（内置函数/局部闭包没有 `__name__` 时退回类名）。"""
    name = getattr(hook, "__name__", "")
    return str(name) if name else type(hook).__name__


async def call_tool(
    name: str,
    payload: dict[str, Any],
    *,
    hooks: Sequence[Hook] = (),
) -> dict[str, Any]:
    """按白名单同进程直调一个润色工具；`hooks` 在调用**之前**串行执行。

    签名刻意保持 `(name, payload)` 两位置参数 ⇒ `functools.partial(call_tool, hooks=[...])`
    可直接当作 Task 4 `run_polish_loop(dispatch=...)` 的分发器。

    三种出口（**都不抛**，与 `polish_loop._make_default_dispatch` 同形）：

    - 钩子拒绝 ⇒ `{"error": "<原因>", "rejected": True, "hook": "<钩子名>"}`；
    - 未知工具名 ⇒ `{"error": "未知工具 '<name>'", "available": [...]}`；
    - 正常 ⇒ 工具自己的 dict。

    钩子链 **fail-fast**：每个钩子拿到独立的 `dict(payload)` 顶层快照，改写该 dict 不会
    改到后续钩子或工具收到的被审对象；第一个抛异常的钩子即终止，后面的钩子不再执行，
    工具也**不会**被调用（被拒 ≠ 降级放行 —— 权限闸被绕过比调用失败危险得多）。
    """
    for hook in hooks:
        try:
            hook(name, dict(payload))
        except Exception as exc:  # 宽捕是刻意的：钩子是外部注入的，任何异常都只构成"拒绝理由"
            return {
                "error": f"工具 '{name}' 调用被前置钩子拒绝: {_brief(exc)}",
                "rejected": True,
                "hook": _hook_name(hook),
            }

    fn = POLISH_TOOL_ALLOWLIST.get(name)
    if fn is None:
        # errors-as-messages：模型拿到清单后能自己改过，而不是把循环炸掉。
        return {"error": f"未知工具 '{name}'", "available": sorted(POLISH_TOOL_ALLOWLIST)}

    # 工具自身的异常**原样冒泡**：调用方（polish_loop）已有 errors-as-messages 兜底，
    # 这里再吞一层会把"工具坏了"伪装成"权限拒绝"。
    return await fn(payload)
