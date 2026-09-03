# Ledger: DeLector 全仓库审计修复（M1–M5）

> 对应计划：`docs/plans/2026-09-03-audit-hardening-m1-m5.md`
> 执行引擎：vault-exec（降级模式——本环境无写码子代理、无 `scripts/vault_exec_state.py` CLI，
> 由编排者主线程直写 + TDD，每 Task 原子提交；maker-checker 由只读 code-explorer 复审）。
> 开始：2026-09-03

## 执行日志

| Task | 内容 | 状态 | commit | 复审 |
|---|---|---|---|---|
| M1-1 | 还原不导入 API_BASE_URL/API_MODEL | pending | — | — |
| M1-2 | X-WB-Key 恒定时间比较 + 共享 helper | pending | — | — |
| M1-3 | 批注删除补本机闸 | pending | — | — |
| M1-4 | TTS 错误收敛 + voice 白名单 + 输入上限 | pending | — | — |
| M1-5 | Anki 导出 HTML 转义 | pending | — | — |
| M2-1 | 补 7 条索引 | pending | — | — |
| M2-2 | stats/趋势/streak 单扫 | pending | — | — |
| M2-3 | list 减载 + review 去回查 | pending | — | — |
| M2-4 | closing ctx 全局替换 | pending | — | — |
| M3-1 | notify + api 超时 + alert 收敛(首批) | pending | — | — |
| M3-2 | reader/writer/cards 陈旧守卫 | pending | — | — |
| M3-3 | player blob URL 生命周期 | pending | — | — |
| M3-4 | PWA 温和更新 | pending | — | — |
| M4-1 | 模块级常量提升 | pending | — | — |
| M4-2 | split_komposita/core 查表缓存 | pending | — | — |
| M4-3 | 从句拓扑去重（可选） | pending | — | — |
| M5-1 | 6 测试模块 DB 隔离 | pending | — | — |
| M5-2 | workbench/写作测试护栏 | pending | — | — |
| M5-3 | 前端 P2 小修 + alert 收敛 | pending | — | — |
| M5-4 | server __all__ 收口 | pending | — | — |

## 降级声明

本环境无写码子代理（task 仅只读 code-explorer），Zero-Edit Iron Rule 无法满足；
`scripts/vault_exec_state.py` 不存在。按计划「执行模式说明」降级为主线程直写 + TDD，
每 Task RED→GREEN→REFACTOR→原子 commit，diff 交 code-explorer 只读复审后记入上表。
不伪造子代理执行记录。
