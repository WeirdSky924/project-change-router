# Project Change Router Skill

中文默认版。英文版见 [README.en.md](./README.en.md)。

`project-change-router` 是一个面向大型仓库的独立 AI coding skill，可用于 Codex 和 Claude Code。它用于在真正修改代码之前，判断当前变更应该：

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
- 可选的仓库级 profile 覆盖

## 能力说明

这个 skill 可以：

- 将变更路由到正确的能力入口
- 降低重复实现
- 检查依赖方向和 public API 边界
- 为仓库生成本地 router bundle
- 读取仓库级 `.project-change-router.yaml` 覆盖能力与 owner 规则
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

Codex 安装路径：

```text
%USERPROFILE%\.codex\skills\project-change-router
```

Claude Code 安装路径：

```text
%USERPROFILE%\.claude\skills\project-change-router
```

Python 要求：

- Python `>= 3.10`

安装依赖：

```powershell
pip install -r requirements.txt
```

或者：

```powershell
pip install -e .[dev]
```

安装脚本：

```powershell
python scripts/install_skill.py --target both --inject-hints
```

这个脚本会：

- 安装到 Codex 的 `~/.codex/skills/project-change-router`
- 安装到 Claude Code 的 `~/.claude/skills/project-change-router`
- 向 Codex 的 `~/.codex/AGENTS.md` 追加一段提示词，帮助对话时更容易显式触发该 skill
- 向 Claude Code 的 `~/.claude/CLAUDE.md` 追加一段提示词，帮助对话时更容易显式触发该 skill

## 安装校验

运行：

```powershell
python <codex-home>\skills\.system\skill-creator\scripts\quick_validate.py <codex-home>\skills\project-change-router
```

期望输出：

```text
Skill is valid!
```

本地最小 smoke test：

```powershell
python -m pytest tests/test_router_core.py -q
python scripts/bootstrap_router.py --repo <repo-root> --format json
python scripts/validate_router_bundle.py --repo <repo-root> --format json
python scripts/run_evaluation.py --repo <repo-root> --format json
```

## 使用方式

在 Codex 请求里显式调用：

- `Use $project-change-router to bootstrap a router bundle for this repository.`
- `Use $project-change-router to resolve the correct capability entry for this change.`
- `Use $project-change-router to validate the repository-local router bundle.`

在 Claude Code 中，推荐显式调用：

- `/project-change-router bootstrap a router bundle for this repository`
- `/project-change-router resolve the correct capability entry for this change`
- `/project-change-router validate the repository-local router bundle`

触发方式说明：

- 当前默认仍然是“显式触发优先”
- 也就是在对话中直接写：
  - Codex：`$project-change-router`
  - Claude Code：`/project-change-router`
- 如果你使用 `install_skill.py --inject-hints`，它会：
  - 在 Codex 的 `AGENTS.md` 里追加一段提示词
  - 在 Claude Code 的 `CLAUDE.md` 里追加一段提示词
- 这是一种“伪强制”提醒，但仍然不是后台自动执行

安装后识别验证：

- Codex 中发送：`Use $project-change-router to resolve the correct capability entry for this change.`
- Claude Code 中发送：`/project-change-router resolve the correct capability entry for this change`

期望现象：

- agent 会先检查仓库根目录和 `project-change-router/` bundle
- 如果 bundle 已存在，会直接读取
- 如果 bundle 不存在，只有在你明确要求 bootstrap 时才创建

## 运行模式

- 只读模式：`resolve_entry.py`、`check_reuse.py`、`check_deps.py`、`check_public_api.py`、`check_index_freshness.py`、`run_evaluation.py`
- 写入模式：`bootstrap_router.py`、`rebuild_index.py`

建议默认使用只读模式；只有在用户明确要求生成或刷新仓库本地 bundle 时，才执行写入模式。

## 仓库阶段策略

这个 skill 现在会根据仓库成熟度推断 `repo_stage`，并据此限制路由强度。

阶段：

- `seed`
- `emerging`
- `structured`
- `governed`

对应原则：

- `seed`：默认只给 `new` / `review`
- `emerging`：允许有限 `reuse`，`extend` / `extract` 明显收紧
- `structured`：完整启用 `reuse` / `extend` / `extract`
- `governed`：以 profile 和 guardrail 为主

同时每个 capability 也有自己的 `stage`：

- `provisional`
- `candidate`
- `stable`
- `governed-capability`

早期仓库时，不要把 generated capability / owner / public entry 当正式架构事实。

Route 输出现在还会显式给出：

- `decision_basis`
- `routing_confidence`
- `routing_confidence_level`
- `decision_confidence`
- `decision_confidence_level`
- `confidence_level`
- `confidence_reasons`
- `veto_reasons`
- `positive_signals`
- `negative_signals`
- `risk_signals`
- `recommended_next_action`
- `recommended_next_steps`
- `why_not_actions`

建议解释：

- `high`：有较强 profile / 边界 / 结构证据
- `medium`：有部分结构证据，但仍需谨慎
- `low`：证据不足，默认应理解为 `review`

注意：

- `routing_confidence` 表示“自动落到某个 capability 的证据强度”
- `decision_confidence` 表示“当前 action 本身是否应被执行/停止的把握”
- 因此在 `seed` 仓里出现：
  - `action = review`
  - `routing_confidence = 0.0 ~ 0.25`
  - `decision_confidence = high`
  是合理的

使用建议：

- 优先看 `recommended_next_action`
- 再看 `recommended_next_steps`
- 如果要理解为什么不是别的动作，看 `why_not_actions`

## 生命周期

推荐按下面的决策表使用：

- 初次接入仓库：`python scripts/bootstrap_router.py --repo <repo-root>`
- 仓库结构大改后：`python scripts/rebuild_index.py --repo <repo-root>`
- 提交前校验：`python scripts/validate_router_bundle.py --repo <repo-root>`
- 日常 guardrail 检查：`python scripts/check_reuse.py --repo <repo-root>`、`python scripts/check_deps.py --repo <repo-root>`、`python scripts/check_public_api.py --repo <repo-root>`
- 路由质量回顾：`python scripts/run_evaluation.py --repo <repo-root>`
- 规则优化建议汇总：`python scripts/sync_feedback.py --repo <repo-root>`

人工确认回写：

```powershell
python scripts/sync_feedback.py --repo <repo-root> --feedback-file <feedback.json> --format json
```

`feedback.json` 可以包含：

```json
{
  "decision_id": "route-...",
  "final_action": "review",
  "final_capability": "billing",
  "confirmed_public_entry": "services/billing/__init__.py",
  "confirmed_owner": "billing-team",
  "profile_update_recommended": true,
  "notes": "Human-confirmed correction"
}
```

## 仓库本地 Bundle

skill 本体是全局的。  
生成出来的 `project-change-router/` 是目标仓库自己的本地 bundle。

示例：

```powershell
python <codex-home>\skills\project-change-router\scripts\bootstrap_router.py --repo <repo-root> --format json
```

执行后会在目标仓库里生成：

```text
<repo>/project-change-router/
```

用于保存该仓库自己的引用数据、schema 和报告。

同时会自动把下面这一行追加到目标仓库的 `.gitignore`：

```text
project-change-router/
```

可选地，目标仓库根目录还可以放这些覆盖文件之一：

```text
.project-change-router.yaml
.project-change-router.yml
project-change-router.profile.yaml
project-change-router.profile.yml
```

这些文件可用于声明：

- capability 到路径的映射
- owner 规则
- 风险规则
- module 覆盖规则

现成最小模板见：

- [examples/profiles/README.md](./examples/profiles/README.md)
- [examples/profiles/early-repo.project-change-router.yaml](./examples/profiles/early-repo.project-change-router.yaml)
- [examples/profiles/python-monorepo.project-change-router.yaml](./examples/profiles/python-monorepo.project-change-router.yaml)
- [examples/profiles/ts-workspace.project-change-router.yaml](./examples/profiles/ts-workspace.project-change-router.yaml)
- [examples/profiles/mixed-repo.project-change-router.yaml](./examples/profiles/mixed-repo.project-change-router.yaml)

真实结构匿名校准参考见：

- [examples/calibration/README.md](./examples/calibration/README.md)
- [examples/calibration/anonymized-structure.md](./examples/calibration/anonymized-structure.md)
- [examples/calibration/anonymized-profile.yaml](./examples/calibration/anonymized-profile.yaml)
- [examples/calibration/anonymized-module-map.yaml](./examples/calibration/anonymized-module-map.yaml)
- [examples/calibration/anonymized-route-cases.yaml](./examples/calibration/anonymized-route-cases.yaml)
- [examples/calibration/anonymized-feedback.json](./examples/calibration/anonymized-feedback.json)

## Bundle 样例

完整最小样例见：

- [examples/bundle/router-config.yaml](./examples/bundle/router-config.yaml)
- [examples/bundle/references/capability-catalog.yaml](./examples/bundle/references/capability-catalog.yaml)
- [examples/bundle/references/module-map.yaml](./examples/bundle/references/module-map.yaml)
- [examples/bundle/references/ownership.yaml](./examples/bundle/references/ownership.yaml)
- [examples/bundle/references/change-rules.yaml](./examples/bundle/references/change-rules.yaml)
- [examples/bundle/references/exception-registry.yaml](./examples/bundle/references/exception-registry.yaml)
- [examples/bundle/references/evaluation-set.yaml](./examples/bundle/references/evaluation-set.yaml)

## 输出样例

真实样例见：

- route report: [examples/outputs/resolve-entry.pass.json](./examples/outputs/resolve-entry.pass.json)
- seed new capability route: [examples/outputs/resolve-entry.seed-new-capability.json](./examples/outputs/resolve-entry.seed-new-capability.json)
- `check_deps.py`: [examples/outputs/check-deps.pass.json](./examples/outputs/check-deps.pass.json)
- `check_public_api.py`: [examples/outputs/check-public-api.pass.json](./examples/outputs/check-public-api.pass.json)
- `check_reuse.py`: [examples/outputs/check-reuse.pass.json](./examples/outputs/check-reuse.pass.json)
- `run_evaluation.py`: [examples/outputs/run-evaluation.pass.json](./examples/outputs/run-evaluation.pass.json)

成功输出特征：

- `status: pass`
- 或 route report 中 `action` 为 `reuse` / `extend` / `new` / `review`

常见失败输出特征：

- `status: fail`
- guardrail report 中 `blocking: true`
- route report 中 `review_required: true`
- validation report 中 `errors` 非空

关键字段还包括：

- `decision_basis`
- `routing_confidence`
- `routing_confidence_level`
- `decision_confidence`
- `decision_confidence_level`
- `confidence_level`
- `confidence_reasons`
- `veto_reasons`
- `primary_capability_stage`
- `recommended_next_action`
- `recommended_next_steps`
- `why_not_actions`

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
- 通用逻辑在全局 skill 中，仓库特例通过 profile 覆盖表达，不再硬编码进脚本
- 自动生成的 bundle 仍然建议由仓库维护者继续人工整理

## 边界与误判

这个 skill 是“启发式 + profile 驱动”的路由器，不是绝对精确的架构事实系统。

需要明确：

- 首次 bootstrap 只是 first pass
- capability / ownership / public API 需要人工校准
- `route=review` 不是失败，而是保护机制
- 没有 profile 时，结果会偏保守
- evaluation 通过不代表完全替代人工架构判断
- 早期仓库会被降到更保守的 `repo_stage`
- `provisional` capability 不应该被当成长期边界
- `generated_only` evaluation 只能说明系统自洽，不代表架构已成熟

## 已完成验证

这份 skill 已经完成以下验证：

- skill 结构校验
- skill 自带单元测试
- 在 Java、Python、TypeScript、mixed monorepo fixture 上执行 bootstrap 与 bundle 校验
- 在仓库级 profile 覆盖场景下执行 capability/owner 覆盖验证
- 仓库内 CI 执行依赖安装、测试和 smoke test

## English Version

See [README.en.md](./README.en.md).
