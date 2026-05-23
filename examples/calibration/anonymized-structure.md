# Anonymized Real-World Structure

来源：

- 一个真实存在的项目仓库
- 使用 Python 后端 + React/TypeScript 前端
- 这里仅保留结构角色，不保留原始项目名称和业务术语

## Top-Level Layout

```text
real-world-reference/
  backend/
    api/
    data/
    database/
    models/
    services/
      context_runtime/
      workflow_adapters/
    utils/
  frontend/
    src/
      api/
      components/
      contexts/
      hooks/
      pages/
      types/
      utils/
  migrations/
  scripts/
  skills/
  tests/
```

## Observed Backend Patterns

- 一个集中式 `api` 入口负责挂载 routes
- 大量业务逻辑位于 `services/`
- `services/context_runtime/` 是一个内聚的上下文构建子系统
- `services/workflow_adapters/` 是 workflow 集成边界
- `models/`、`database/`、`data/` 分别承担模型、持久化和种子/静态数据角色

## Observed Frontend Patterns

- `src/api/` 作为后端访问边界
- `src/components/` 内有多个功能子域
- `src/pages/` 形成页面级入口
- `src/contexts/` 和 `src/hooks/` 提供横切状态与行为

## Why This Case Matters

这个真实案例说明：

- service 层很容易在没有 profile 的情况下被过度合并
- `context`、`workflow`、`adapter` 这类目录名在真实仓库里确实存在，但不该只靠名字直接固化 capability
- 前后端、adapter、shared runtime 共同存在时，纯启发式很容易误判

因此更适合用它来校准：

- `ownership_rules`
- `module_overrides`
- 少量高价值 capability 映射
