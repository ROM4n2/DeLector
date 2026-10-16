# WORKMEMORY INDEX — 主题索引与蒸馏登记（WARM 层）

> 本文件由 `INDEX.md` 于 2026-10-17 拆出（热层 MUST 保持极小）。
> 用法（协议 §3）：`grep -i "<关键词>" WORKMEMORY/INDEX-topics.md` → 只加载命中的 archive 分片 / vault 路径，**禁止通读全部历史**。

## 主题索引（archive / digest 内容导航）

> 查旧主题：先在此按关键词定位，再只加载命中的 archive 分片 / digest，**禁止通读全部历史**（协议 §3）。

| 主题                                                                        | 来源文件                                                                                              |
| --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| WORKMEMORY 协议 bootstrap / 跨 agent 记忆约定                               | `archive/work-2026-09-04.log` · `cold/digest-2026-09.md`                                              |
| 备考域重布局 / 工作台 Editorial 重塑 / 语法雷达 / A2 词汇（ADR-0005~0007）  | `archive/work-2026-09-04.log` · `archive/work-2026-09-05.log`                                         |
| Python 包内重构 Phase 1 / Phase 2 收包 / Go Agent Runtime（ADR-0008/0009）  | `archive/work-2026-09-06.log` · `archive/work-2026-09-07.log`                                         |
| 遇见区 P0 + Go DAG job#1（ADR-0010）                                        | `archive/work-2026-09-07.log` · `archive/work-2026-09-08.log`                                         |
| CI Hardening / Ruff / Mypy 静态门禁                                         | `archive/work-2026-09-09.log` · `archive/work-2026-09-13.log`                                         |
| 内容供给侧 / 预置分级短文 / A7 验收自动化                                   | `archive/work-2026-09-10.log`                                                                         |
| WiFi 手机拉取式内容分发                                                     | `archive/work-2026-09-13.log`                                                                         |
| 听力微训 / 长难句精读工坊 + v5.7.x 真机热修（含 spaCy E050 / pydantic v1）  | `archive/work-2026-09-13.log` · `archive/work-2026-09-14.log` ~ `archive/work-2026-09-15.log`（2026-10-11 WARM 化） |
| 词库单一真相化 / 主干分层 / 富字段 / A1 取数（ADR-0011~0015，v5.8.0~v5.10.0） | `cold/digest-2026-09.md` · `archive/work-2026-09-15.log` ~ `archive/work-2026-09-17.log`（09-15 ~ 09-17，2026-10-11 WARM 化）· `work.log`（09-18 ~ 09-21） |
| 遇见区 i+1 / 已读状态 + 工程债收口（v5.11.0~v5.12.1）                       | `cold/digest-2026-09.md` · `work.log`（2026-09-23 ~ 09-26）                                           |
| **2026 年 10 月全月**（v5.14.0~v5.17.0 四次发版 / ADR-0017~0024 决策链 / 裁判集扩充 / §4.3 对照实验 60 局真跑 / 审计修正 A+B 批 / `database.py` 切分） | **`cold/digest-2026-10.md`**（COLD 层蒸馏；细节回源见该文件末节「来源」） |
| 2026-09-28 起（Docker/WAL 修复、ADR-0016 统一池 Phase 3 等，未发版）        | `work.log`（HOT；09-28 起的记录缺口由 10-02 的 2 条 `NOTE(gap-backfill-1/2)` 补记；细节见 `docs/reviews/2026-09-28-swarm-audit-master.md`） |
| ADR-0023 交互层「验证驱动 agent 循环」Task 0~6（Go 门禁三红灯 / LLM 收口 / 循环内核 / 工具白名单 / 契约+前端） | `archive/work-2026-10-14.log` · `work.log`（10-15~10-16 段）· 计划正本 `docs/plans/2026-10-14-interactive-agent-loop.md` · PR #136 |
| Fog 清空（2/3/4）+ v5.16.0 发版 + search 高亮递延项（2026-10-06）            | `archive/work-2026-10-06.log`（2026-10-16 WARM 化） |
| ADR-0017 Android 更新可见性（/dfs-grill）+ 实施（2026-10-08）                | `archive/work-2026-10-08.log` · `work.log`（10-08 11:12 EXEC 那条） |
| Windows 桌面端决策链 ADR-0019/0020/0021 + 前端跨边界契约闸 + 桌面壳实机验收（2026-10-10） | `archive/work-2026-10-10.log`（2026-10-16 WARM 化） |
| 首屏性能测量（6s / 端口探测 2s）/ 未测段可观测化 / 仓库根数据目录卫生 / ADR-0022 发版门 / v5.17.0 发版（2026-10-11） | `archive/work-2026-10-11.log`（2026-10-16 WARM 化） |
| 薄壳落地页（宣传延后）/ release 文档合并 / 孤儿 tag 清理 / 子进程超时反转修复（2026-10-12） | `archive/work-2026-10-12.log`（2026-10-16 WARM 化） |
| 去控制台 + 桌面化观感收尾 / 直推 master 流程缺陷复盘（2026-10-13~14）        | `archive/work-2026-10-13.log` · `archive/work-2026-10-14.log`（2026-10-16 WARM 化） |
| 非在途面专家评估（5 报告）+ 未决项 18 项 + 审计修正 A/B 两批 + ADR-0024 + `database.py` 切分（2026-10-16） | `work.log`（10-16 段）· `docs/reviews/2026-10-16-open-items-backlog.md` · `docs/plans/2026-10-16-audit-fixes-a-series.md` · `docs/plans/2026-10-16-audit-fixes-b-series.md` · `docs/plans/2026-10-16-database-split.md` |


## 蒸馏登记（WORKMEMORY → vault）

| 日期       | 主题                                                                         | vault 归属                                                                                                    |
| ---------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| 2026-09-04 | 跨端 Python 打包孤岛治理：Chaquopy 与 PyInstaller 模块同步与 CI 自动守卫机制 | `vault://99-Inbox/2026-09-04-跨端-python-打包孤岛治理：chaquopy-与-pyinstaller-模块同步与-ci-自动守卫机制.md` |
| 2026-09-05 | 德语词法数据全域规范化与多等级卡片模板单源防呆 | `vault://99-Inbox/2026-09-05-德语词法数据全域规范化与多等级卡片模板单源防呆.md` |
| 2026-10-16 | 搬包后 `__file__` 派生路径静默偏层：导出常量的「值」也是冻结面（并入 `PYTHON-PACKAGING §2`） | `vault://99-Inbox/2026-10-16-搬包后-__file__-派生路径静默偏层：导出常量的「值」也是冻结面.md` |
| 2026-10-16 | 结构重构后 patch 触达失效：monkeypatch 必须打在「被调用方所在模块」（并入 `TESTING-PATTERNS §7`） | `vault://99-Inbox/2026-10-16-结构重构后-patch-触达失效：monkeypatch-必须打在「被调用方所在模块」.md` |
| 2026-10-16 | 本地验证≠CI 门禁：近似命令不算复刻（并入 `CODING-UNIVERSAL §7`） | `vault://99-Inbox/2026-10-16-本地验证≠ci-门禁：近似命令不算复刻（单文件-vs-整目录-+-目标集差异）.md` |
| 2026-10-16 | 嵌套子进程的递归炸弹与令牌化哨兵（新增 `AUTOMATION-GOTCHAS §7`） | `vault://99-Inbox/2026-10-16-嵌套子进程测试的递归炸弹：守卫用例把「整个模块」当子进程目标-⇒-无界进程链.md` |
