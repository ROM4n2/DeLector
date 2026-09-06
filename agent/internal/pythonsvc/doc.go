// Package pythonsvc 封装 Go Agent Runtime 与 Python NLP 微服务的全部交互。
//
// 职责分两块（按 Phase 2a 计划逐步落地）：
//
//   - Client：HTTP 客户端，调用 POST /api/tools/{name}，body 为
//     {"payload": {...}}；错误映射 404→ErrToolNotFound、400→*ToolError、
//     非 localhost 403。全部请求经 NewRequestWithContext + 显式超时
//     （Phase 2a Task 2）。
//   - Supervisor：Python 常驻进程管理，127.0.0.1:8001（8000 留给用户
//     直启实例），健康探针 /api/tools/，crash 指数退避重启，优雅关闭
//     （Phase 2a Task 5）。
//
// 契约即法律：工具清单以 Python 侧 delector/tools/__init__.py 的
// TOOL_REGISTRY 为准 —— ingest / analyze / writing_check / export / tts
// 共 5 个（exercise 已更名 writing_check，见 ADR-0009；review 工具
// Python 侧尚不存在）。
//
// 架构见 docs/specs/2026-09-06-adr-0008-go-agent-runtime-architecture.md。
package pythonsvc
