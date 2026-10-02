# WORKMEMORY INDEX — DeLector

## Configuration

- HOT_RETENTION_EVENTS: 50 # work.log 热层保留事件数；轮转阈值 = 本值 × 1.5

## 文件清单

| 文件                  | 职责                                                          |
| --------------------- | ------------------------------------------------------------- |
| `PROTOCOL.md`         | 协议本体（读一次即可，之后按本索引工作）                      |
| `PROJECT_OVERVIEW.md` | 60 秒项目 primer（新 agent 第二读）                           |
| `work.log`            | HOT 事件流（append-only，最近 50 条；第三读）                 |
| `archive/`            | WARM 层（按日分片 `work-YYYY-MM-DD.log`，只按下方索引按需加载） |
| `cold/`               | COLD 层（按月 digest，当前 `digest-2026-09.md`）              |
| `corrections.md`      | 纠正账本（追加制）：记录用户纠正，顶部 open 条目是会话开工必读的 Anchor 读序最后一站（协议 §2.1）；成熟条目蒸馏入 vault 后置 `closed` |
| `handoff_*.md`        | 跨 agent 交接包（**按需出现**：仅当存在活跃交接时才存在，非常驻文件；协议 §4） |

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
| 听力微训 / 长难句精读工坊 + v5.7.x 真机热修（含 spaCy E050 / pydantic v1）  | `archive/work-2026-09-13.log` · `archive/work-2026-09-14.log` · `work.log`（延续）                    |
| 词库单一真相化 / 主干分层 / 富字段 / A1 取数（ADR-0011~0015，v5.8.0~v5.10.0） | `cold/digest-2026-09.md` · `work.log`（2026-09-15 ~ 09-21）                                           |
| 遇见区 i+1 / 已读状态 + 工程债收口（v5.11.0~v5.12.1）                       | `cold/digest-2026-09.md` · `work.log`（2026-09-23 ~ 09-26）                                           |
| 2026-09-28 起（Docker/WAL 修复、ADR-0016 统一池 Phase 3 等，未发版）        | `work.log`（HOT；09-28 起的记录缺口由 10-02 的 2 条 `NOTE(gap-backfill-1/2)` 补记；细节见 `docs/reviews/2026-09-28-swarm-audit-master.md`） |

## Active handoffs

（无）

## 蒸馏登记（WORKMEMORY → vault）

| 日期       | 主题                                                                         | vault 归属                                                                                                    |
| ---------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| 2026-09-04 | 跨端 Python 打包孤岛治理：Chaquopy 与 PyInstaller 模块同步与 CI 自动守卫机制 | `vault://99-Inbox/2026-09-04-跨端-python-打包孤岛治理：chaquopy-与-pyinstaller-模块同步与-ci-自动守卫机制.md` |
| 2026-09-05 | 德语词法数据全域规范化与多等级卡片模板单源防呆 | `vault://99-Inbox/2026-09-05-德语词法数据全域规范化与多等级卡片模板单源防呆.md` |
