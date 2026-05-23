# Project Change Router Skill

中文默认版。英文版见 [README.en.md](./README.en.md)。

`project-change-router` 是一个面向大型仓库的独立 Codex skill。它用于在真正修改代码之前，判断当前变更应该：

- `reuse`
- `extend`
- `extract`
- `new`
- `review`

这个 skill 安装在全局 skill 目录下，不依赖某个固定项目。  
它也可以为目标仓库生成一个本地 `project-change-router/` bundle，里面包含：

- 路由配置
- capability catalog
- module map
- ownership map
- 路由规则
- exception registry
- evaluation set
- schema 校验文件

## 能力说明

这个 skill 可以：

- 将变更路由到正确的能力入口
- 降低重复实现
- 检查依赖方向和 public API 边界
- 为仓库生成本地 router bundle
- 用 JSON Schema 校验 bundle
- 执行路由评估集
- 从路由结果和 guardrail 报告中生成反馈建议

## 目录结构

```text
project-change-router/
  SKILL.md
  README.md
  README.en.md
  agents/openai.yaml
  assets/
  references/
  schemas/
  scripts/
  tests/
```

## 安装方式

把整个目录复制或 clone 到：

```text
C:\Users\<你的用户>\.codex\skills\project-change-router
```

当前机器上的安装路径是：

```text
C:\Users\dell\.codex\skills\project-change-router
```

## 安装校验

运行：

```powershell
python C:\Users\dell\.codex\skills\.system\skill-creator\scripts\quick_validate.py C:\Users\dell\.codex\skills\project-change-router
```

期望输出：

```text
Skill is valid!
```

## 使用方式

在 Codex 请求里显式调用：

- `Use $project-change-router to bootstrap a router bundle for this repository.`
- `Use $project-change-router to resolve the correct capability entry for this change.`
- `Use $project-change-router to validate the repository-local router bundle.`

## 仓库本地 Bundle

skill 本体是全局的。  
生成出来的 `project-change-router/` 是目标仓库自己的本地 bundle。

示例：

```powershell
python C:\Users\dell\.codex\skills\project-change-router\scripts\bootstrap_router.py --repo E:\_Workspace\SaaS\saas-control-plane --format json
```

执行后会在目标仓库里生成：

```text
<repo>/project-change-router/
```

用于保存该仓库自己的引用数据、schema 和报告。

## 主要脚本

- `scripts/bootstrap_router.py`
- `scripts/resolve_entry.py`
- `scripts/rebuild_index.py`
- `scripts/check_reuse.py`
- `scripts/check_deps.py`
- `scripts/check_public_api.py`
- `scripts/check_index_freshness.py`
- `scripts/run_evaluation.py`
- `scripts/sync_feedback.py`
- `scripts/validate_router_bundle.py`

## 设计说明

- 这是一个独立 skill，不绑定单个仓库
- 本地 bundle 按需生成，不是 skill 本体的一部分
- 对高风险共享能力会采取更保守的 `review` 路由策略
- 自动生成的 bundle 仍然建议由仓库维护者继续人工整理

## 已完成验证

这份 skill 已经完成以下验证：

- Codex skill 结构校验
- skill 自带单元测试
- 在真实 Java 仓库和 Python/TypeScript 仓库上执行 bootstrap 与 bundle 校验

## English Version

See [README.en.md](./README.en.md).
