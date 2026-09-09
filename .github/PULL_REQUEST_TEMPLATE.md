<!-- 标题格式：feat|fix|test|refactor|docs|ci(scope): 中文描述 -->

## 变更摘要

<!-- 一句话说清做了什么、为什么（关联 Issue / 计划文档请在此链接） -->

## 门禁证据

<!-- 合并前必须贴命令与结果末行；缺证据的 PR 不予合并 -->

```text
# Python 全量（仓库根）
$ pytest -q
# 末行：

# Go 门禁（agent/）
$ go vet ./... && gofmt -l . && go test -race ./...
# 末行：
```

## 自查清单

- [ ] 新路由/新工具已同步打包注册守卫（routes / TOOL_REGISTRY / APP_NEEDLES）
- [ ] 跨边界契约有行为探针（非字符串死断言）
- [ ] 敏感设置/删除类端点过 `_require_localhost` 闸
- [ ] 版本面无影响（或已同步五件套：sw.js / index.html / build.gradle / README / OVERVIEW）
- [ ] `pytest -q` 与 `go test -race ./...` 本地全绿
