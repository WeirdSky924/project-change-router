# Project Change Router Skill

中文默认版。英文版见 [README.en.md](./README.en.md)。

`project-change-router` 是一个面向大型仓库的 AI coding skill，可用于 Codex 和 Claude Code。它的目标不是让 agent 更大胆地猜架构，而是让 agent 更少乱猜：在真正修改代码之前，先用仓库本地的路由 bundle 获取能力归属、canonical root、owner、读写边界、复用风险和处理倾向。

它解决的核心问题是大型项目开发中常见的结构漂移：

- agent 上下文有限，不可能每次完整读取大型全栈项目。
- agent 注意力会漂移，容易只根据局部文件和名字相似做判断。
- 可复用能力可能被重复实现，形成第二套平行中心。
- 本该进入底层共享能力的代码可能被写到 facade、API、UI 或临时目录里。
- 空仓、早期仓和重构仓的边界不稳定，自动推断很容易把临时结构当成长期架构事实。

这个 skill 提供的是一个低 token、可验证、可校准的“项目变更方向索引与边界护栏”。它不替代 agent 的详细工程分析，也不替用户做最终架构决策；它负责在动手前给出路线、证据、强约束、风险原因和后续校准方向。

![Project Change Router overview](./assets/readme-hero.svg)

## 核心理念

这个项目的设计原则是：

- 少乱猜优先于更聪明地猜。证据不足时宁可 `review`，不要伪装成确定结论。
- profile 优先于纯启发式。真实 owner、public entry、capability 边界和 path pattern 应逐步写入 `.project-change-router.yaml`。
- 结构证据优先于名字相似。路径、owner、public API、依赖关系、测试绑定比语义相似更可靠。
- 早期仓库默认保守。`seed` / `emerging` 阶段不应轻易自动 `extend` 或 `extract`。
- `review` 不是失败。它是保护机制，表示当前不能安全自动写代码，但可以进行只读分析和人工确认。
- 路由输出是一体化契约。强约束字段必须遵守，`action` 和解阻建议用于辅助判断，不能替代源码分析。
- 结果必须能持续变准。人工 override、误判、profile 修正和真实案例应沉淀到 feedback 与 evaluation。

## 两层使用模型

PCR 的输出分为两层，使用时不要混在一起理解。

必须执行层：

- 必须尊重 `allowed_write_paths`、`forbidden_write_paths` 和 `must_read_before_edit`。
- 必须识别并保护已有 owner、public entry、canonical root 和依赖方向。
- 不能在已有能力可能存在时新建第二套平行实现中心。
- 出现 `veto_reasons`、生命周期 review、低路由置信度、provisional 边界、高风险重叠时，必须先停下做确认、只读分析或 profile 修复，再写产品代码。

参考建议层：

- `action` 是当前证据下的处理倾向，不是最终工程命令。
- `recommended_next_steps`、`safe_next_steps`、`analysis_directions`、`why_not_actions` 和 `profile_repair_hints` 是解阻方向和调查提示。
- `action=review` 不等于永远不能做；它表示当前证据不足以自动写代码，需要补证据、补 profile、读源码、请求 scoped override 或进入更高级 gate。
- 最终实现方案仍必须来自真实源码分析、依赖追踪、测试和用户确认。

## 能力范围

这个 skill 可以：

- 为目标仓库生成本地 `project-change-router/` bundle。
- 识别仓库模块、capability、owner、public entry、路径归属和依赖方向。
- 根据请求和 changed paths 输出 route report，包含强约束和建议动作。
- 对重复实现、错误边界、public API 绕过和依赖方向问题做 guardrail 检查。
- 通过 `path-to-capability-map.yaml` 暴露路径归属、共享归属和未覆盖模块。
- 用 schema 校验 bundle 与报告。
- 用 evaluation set 检查路由质量是否退化。
- 用 governance audit 检查 profile/catalog 同步、ownership 颗粒度、contract 质量、forbidden density、evaluation 覆盖和 capability 生命周期。
- 在 Codex / Claude Code 安装时追加提示块，让 agent 更容易在功能级 create / modify / delete 前主动触发该 skill。

它不应该：

- 替代详细代码阅读、依赖追踪、测试设计和架构分析。
- 把 `action` 当成无需分析即可执行的最终命令。
- 在 `review` 后绕开证据补充、用户确认或 scoped override 自动继续写产品代码。
- 把 generated-only bundle 当作成熟架构事实。
- 因为名字相似就强行复用或扩展已有 capability。
- 在没有确认 canonical root 时创建第二套实现中心。

## 路由动作

`resolve_entry.py` 会输出五类动作。这些动作是处理建议和调查方向，不是最终架构命令：

- `reuse`：使用已有 capability，不修改核心实现。
- `extend`：在已有共享 capability 或兼容扩展点上增加行为。
- `extract`：先把重复逻辑抽到共享 capability，再让调用方复用。
- `new`：没有合适复用目标，应建立新的隔离 capability 边界。
- `review`：证据不足、风险过高或跨多能力，需要补证据、补 profile、人工确认或 scoped override 后再写。

`review` 需要特别理解：它不是“系统没用”，也不是永久阻塞，而是“系统很确定当前不应自动写”。在空仓或早期仓里，可能出现：

```json
{
  "action": "review",
  "routing_confidence": 0.0,
  "routing_confidence_level": "low",
  "decision_confidence": 0.95,
  "decision_confidence_level": "high"
}
```

这表示：系统对“应该落到哪个 capability”没有把握，但对“现在应该先停下来补证据或确认”很有把握。agent 可以继续做只读分析、profile 修复建议、调用方追踪和用户确认，但不应直接写产品代码。

## 仓库阶段策略

router 会根据仓库成熟度推断 `repo_stage`：

- `seed`：空仓或极早期仓，默认只允许明显的新边界或 `review`。
- `emerging`：已有少量结构，但 capability 边界仍保守，provisional 不自动成为强复用目标。
- `structured`：模块边界较稳定，可以更完整地使用 `reuse`、`extend`、`extract`。
- `governed`：以 profile、owner、public entry、evaluation 和 guardrail 为主要依据。

capability 自身也有阶段：

- `provisional`
- `candidate`
- `stable`
- `governed-capability`
- `deprecated`

早期仓库不要过早固化 generated capability。推荐先写最小 ownership/profile，再随着真实开发逐步补 capability、public entry、contract、test binding 和 evaluation case。

## 一体化路由报告

route report 不是只给一个 action。它是一个完整路由契约，核心字段包括：

- `action`
- `decision_basis`
- `routing_confidence`
- `routing_confidence_level`
- `decision_confidence`
- `decision_confidence_level`
- `primary_capability`
- `primary_capability_stage`
- `secondary_capabilities`
- `candidate_capabilities`
- `required_reads`
- `required_checks`
- `recommended_next_action`
- `recommended_next_steps`
- `why_not_actions`
- `confidence_reasons`
- `veto_reasons`
- `positive_signals`
- `negative_signals`
- `risk_signals`

七类治理输出也是同一个 route report 的一等字段，不是外挂能力：

- `review` 后处理：`block_reason`、`missing_evidence`、`analysis_directions`、`safe_next_steps`、`suggested_questions`、`override_requirements`
- 写入约束：`allowed_write_paths`、`forbidden_write_paths`、`must_read_before_edit`
- profile 修复方向：`profile_repair_hints`，治理审计报告中还有 `repair_suggestions`
- 变更后收口：`post_change_closeout`
- 删除、合并、废弃能力治理：`capability_lifecycle_action`
- 跨栈复合路由：`composite_route`
- 真实回归沉淀：`evaluation_regression_hints`

详细契约见 [references/governance-outputs.md](./references/governance-outputs.md)。

![Integrated route contract](./assets/readme-route-contract.svg)

## 安装

Python 要求：

- Python `>= 3.10`

安装依赖：

```powershell
pip install -r requirements.txt
```

或以开发模式安装：

```powershell
pip install -e .[dev]
```

安装到 Codex 和 Claude Code：

```powershell
python scripts/install_skill.py --target both --inject-hints
```

安装路径：

- Codex：`%USERPROFILE%\.codex\skills\project-change-router`
- Claude Code：`%USERPROFILE%\.claude\skills\project-change-router`

`--inject-hints` 会追加标记块，不会重写整个文件：

- Codex：追加到 `~/.codex/AGENTS.md`
- Claude Code：追加到 `~/.claude/CLAUDE.md`

这是一种“伪强制”提醒，用于让 agent 在功能级 create / modify / delete 前主动触发 skill。它不是后台守护进程，也不会绕过对话触发机制。

## 安装校验

校验 skill 结构：

```powershell
python <codex-home>\skills\.system\skill-creator\scripts\quick_validate.py <codex-home>\skills\project-change-router
```

期望输出：

```text
Skill is valid!
```

本仓库完整 smoke：

```powershell
python -m pytest tests/test_router_core.py -q
python scripts/bootstrap_router.py --repo . --format json
python scripts/validate_router_bundle.py --repo . --format json
python scripts/check_bundle_governance.py --repo . --format json
python scripts/check_index_freshness.py --repo . --format json
python scripts/run_evaluation.py --repo . --format json
```

## 在目标仓库接入

首次接入目标仓库：

```powershell
python <skill-root>\scripts\bootstrap_router.py --repo <repo-root> --format json
```

这会在目标仓库生成：

```text
<repo-root>/project-change-router/
```

bundle 包含：

- `router-config.yaml`
- `references/capability-catalog.yaml`
- `references/module-map.yaml`
- `references/ownership.yaml`
- `references/path-to-capability-map.yaml`
- `references/change-rules.yaml`
- `references/exception-registry.yaml`
- `references/evaluation-set.yaml`
- `schemas/`
- `reports/`

bootstrap 会自动把下面这行加入目标仓库 `.gitignore`：

```text
project-change-router/
```

目标仓库根目录可放 profile 覆盖文件：

```text
.project-change-router.yaml
.project-change-router.yml
project-change-router.profile.yaml
project-change-router.profile.yml
```

profile 可声明：

- capability 到路径的映射
- ownership rules
- module overrides
- public entries
- contracts
- forbidden patterns
- lifecycle metadata
- evaluation cases
- risk rules

最小 profile 模板见 [examples/profiles/README.md](./examples/profiles/README.md)。

## 日常使用

Codex 中可以显式触发：

```text
Use $project-change-router to resolve the correct capability entry for this change.
```

Claude Code 中可以显式触发：

```text
/project-change-router resolve the correct capability entry for this change
```

命令行解析一次变更：

```powershell
python scripts/resolve_entry.py --repo <repo-root> --request "Add invoice refund support" --changed-path services/billing/refund.py --format json
```

也可以从请求文件读取：

```powershell
python scripts/resolve_entry.py --repo <repo-root> --request-file request.md --changed-path services/billing/refund.py --format json --output route-report.json
```

解析后执行规则：

- 如果 `action=review`：不要自动写产品代码；先执行 `safe_next_steps`、补证据、做只读分析，必要时向用户请求 scoped override。
- 如果 `action=reuse`：把它当成复用倾向；优先读取 `must_read_before_edit` 和 `required_reads`，不要改核心实现。
- 如果 `action=extend`：把它当成扩展倾向；只在 `allowed_write_paths` 内扩展，避免绕过 public entry。
- 如果 `action=extract`：把它当成抽取倾向；先确认重复面、调用方和测试，再抽共享能力。
- 如果 `action=new`：把它当成新边界倾向；先命名隔离边界，不要在已有 capability 旁边生成第二套平行中心。

## Codex / Claude Code 提示词

建议在无人值守计划或长期任务中加入：

```text
Before any feature-level create, modify, delete, merge, deprecate, or migration work, invoke project-change-router for the target repository. Use it as a direction index and guardrail system, not as an automatic architecture decision engine.

Treat mandatory guardrails as binding: must_read_before_edit, allowed_write_paths, forbidden_write_paths, veto_reasons, canonical root, owner, public entry, lifecycle review, and duplicate-implementation warnings must be respected before product-code writes.

Treat action, recommended_next_steps, safe_next_steps, analysis_directions, profile_repair_hints, and why_not_actions as structured guidance for source-code analysis and user-confirmed decisions, not final architecture commands.

If action=review, do not implement product code automatically. Continue only with safe_next_steps, read-only analysis, profile repair proposals, or a scoped user override for the current task, phase, or changed paths. Do not reuse an override from an earlier phase.

Do not create a second implementation center when an existing capability or canonical root may exist. If routing evidence is weak, repair the profile or ask for confirmation instead of guessing.

After routed changes, run the required closeout checks and record feedback/evaluation cases when a review, override, lifecycle change, or routing correction occurred.
```

更完整的可复制版本见 [examples/agent-workflows/unattended-plan-prompt.md](./examples/agent-workflows/unattended-plan-prompt.md)。

如果目标仓库以前已经用旧版 skill 生成过 `project-change-router/` bundle，升级后让 agent 刷新本地生成文档和路由索引时，使用 [examples/agent-workflows/update-existing-router-bundle-prompt.md](./examples/agent-workflows/update-existing-router-bundle-prompt.md)。它要求只刷新治理元数据和生成提示块，保留人工 profile、反馈、评估样例和生命周期信息。

## 生命周期命令表

| 场景 | 命令 |
| --- | --- |
| 初次接入仓库 | `python scripts/bootstrap_router.py --repo <repo-root> --format json` |
| 仓库结构大改后 | `python scripts/rebuild_index.py --repo <repo-root> --format json` |
| 修改前解析路由 | `python scripts/resolve_entry.py --repo <repo-root> --request "<request>" --changed-path <path> --format json` |
| 提交前校验 bundle | `python scripts/validate_router_bundle.py --repo <repo-root> --format json` |
| 检查重复实现 | `python scripts/check_reuse.py --repo <repo-root> --changed-path <path> --format json` |
| 检查依赖方向 | `python scripts/check_deps.py --repo <repo-root> --format json` |
| 检查 public API 边界 | `python scripts/check_public_api.py --repo <repo-root> --format json` |
| 检查索引新鲜度 | `python scripts/check_index_freshness.py --repo <repo-root> --format json` |
| 路由治理健康检查 | `python scripts/check_bundle_governance.py --repo <repo-root> --format json` |
| 路由质量回归评估 | `python scripts/run_evaluation.py --repo <repo-root> --format json` |
| 人工反馈回写 | `python scripts/sync_feedback.py --repo <repo-root> --feedback-file feedback.json --format json` |

## Reuse 扫描预算

`check_reuse.py` 使用有界扫描，避免单个 changed path 退化成全仓全文相似度比较。

- 优先传入 `--changed-path <path>`；脚本会直接从 changed path 收集候选文件，不会在没有命中 module 时回退全量扫描。
- `summary.scan` 会报告 candidate 数量、owner 文件数量、预筛跳过数、全文比较数、预算和大文件限制。
- `status=warn` 表示扫描因预算或文件大小限制不是穷尽结果，但没有发现 P0/P1 阻断；agent 应结合 `summary.scan` 继续做定向源码分析或收窄 profile。
- 可用 `--max-candidate-files`、`--max-owner-files`、`--max-comparisons`、`--max-file-bytes`、`--top-k-owner-files` 覆盖默认预算。

## 治理审计

`check_bundle_governance.py` 用于检查 bundle 是否只是“能跑”，还是具备长期路由治理质量。

它会检查：

- profile 声明的 capability 是否进入 catalog。
- change rules 是否引用未知 capability。
- generated-only capability 是否过多。
- path-to-capability map 是否存在未覆盖模块或多能力冲突路径。
- ownership rules 是否过宽或过细。
- contracts 是否缺失、过短或过长。
- 大能力的 forbidden patterns 密度是否过低。
- dependency priority 是否覆盖所有 capability。
- evaluation set 是否覆盖 profile-backed capability。
- deprecated capability 是否具备 `superseded_by`、`deprecation_date`、`migration_note`。

默认退出码：

- P0：失败。
- P1：默认 warn，`--strict` 下失败。
- P2：维护建议，不阻塞。

## 人工反馈与持续校准

![Continuous router calibration loop](./assets/readme-feedback-loop.svg)

当发生人工确认、override、误判、能力合并、废弃或 profile 修正时，应记录反馈：

```powershell
python scripts/sync_feedback.py --repo <repo-root> --feedback-file feedback.json --format json
```

示例：

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

推荐把真实误判沉淀为 evaluation case。不要只修规则而不加回归样例。

可复制样例：

- [examples/feedback/manual-route-correction.json](./examples/feedback/manual-route-correction.json)
- [examples/evaluation/route-regression-cases.yaml](./examples/evaluation/route-regression-cases.yaml)

## 真实仓校准参考

匿名真实结构参考见：

- [examples/calibration/README.md](./examples/calibration/README.md)
- [examples/calibration/anonymized-structure.md](./examples/calibration/anonymized-structure.md)
- [examples/calibration/anonymized-profile.yaml](./examples/calibration/anonymized-profile.yaml)
- [examples/calibration/anonymized-module-map.yaml](./examples/calibration/anonymized-module-map.yaml)
- [examples/calibration/anonymized-route-cases.yaml](./examples/calibration/anonymized-route-cases.yaml)
- [examples/calibration/anonymized-feedback.json](./examples/calibration/anonymized-feedback.json)

这些样例用于说明大型全栈项目如何把真实模块、owner、public entry、route case 和反馈沉淀为可复用治理数据。

## 示例文件

Agent 工作流示例：

- [examples/agent-workflows/README.md](./examples/agent-workflows/README.md)
- [examples/agent-workflows/unattended-plan-prompt.md](./examples/agent-workflows/unattended-plan-prompt.md)
- [examples/agent-workflows/update-existing-router-bundle-prompt.md](./examples/agent-workflows/update-existing-router-bundle-prompt.md)

Profile 模板：

- [examples/profiles/early-repo.project-change-router.yaml](./examples/profiles/early-repo.project-change-router.yaml)
- [examples/profiles/python-monorepo.project-change-router.yaml](./examples/profiles/python-monorepo.project-change-router.yaml)
- [examples/profiles/ts-workspace.project-change-router.yaml](./examples/profiles/ts-workspace.project-change-router.yaml)
- [examples/profiles/mixed-repo.project-change-router.yaml](./examples/profiles/mixed-repo.project-change-router.yaml)
- [examples/profiles/skill-repo.project-change-router.yaml](./examples/profiles/skill-repo.project-change-router.yaml)

反馈与评估样例：

- [examples/feedback/manual-route-correction.json](./examples/feedback/manual-route-correction.json)
- [examples/evaluation/route-regression-cases.yaml](./examples/evaluation/route-regression-cases.yaml)

Bundle 样例：

- [examples/bundle/router-config.yaml](./examples/bundle/router-config.yaml)
- [examples/bundle/references/capability-catalog.yaml](./examples/bundle/references/capability-catalog.yaml)
- [examples/bundle/references/module-map.yaml](./examples/bundle/references/module-map.yaml)
- [examples/bundle/references/ownership.yaml](./examples/bundle/references/ownership.yaml)
- [examples/bundle/references/path-to-capability-map.yaml](./examples/bundle/references/path-to-capability-map.yaml)
- [examples/bundle/references/change-rules.yaml](./examples/bundle/references/change-rules.yaml)
- [examples/bundle/references/exception-registry.yaml](./examples/bundle/references/exception-registry.yaml)
- [examples/bundle/references/evaluation-set.yaml](./examples/bundle/references/evaluation-set.yaml)

输出样例：

- [examples/outputs/resolve-entry.pass.json](./examples/outputs/resolve-entry.pass.json)
- [examples/outputs/resolve-entry.review-guidance.json](./examples/outputs/resolve-entry.review-guidance.json)
- [examples/outputs/resolve-entry.composite-review.json](./examples/outputs/resolve-entry.composite-review.json)
- [examples/outputs/resolve-entry.seed-new-capability.json](./examples/outputs/resolve-entry.seed-new-capability.json)
- [examples/outputs/check-deps.pass.json](./examples/outputs/check-deps.pass.json)
- [examples/outputs/check-public-api.pass.json](./examples/outputs/check-public-api.pass.json)
- [examples/outputs/check-reuse.pass.json](./examples/outputs/check-reuse.pass.json)
- [examples/outputs/check-reuse.warn.json](./examples/outputs/check-reuse.warn.json)
- [examples/outputs/check-bundle-governance.warn.json](./examples/outputs/check-bundle-governance.warn.json)
- [examples/outputs/run-evaluation.pass.json](./examples/outputs/run-evaluation.pass.json)

参考文档：

- [references/router-workflow.md](./references/router-workflow.md)
- [references/governance-outputs.md](./references/governance-outputs.md)
- [references/bootstrap.md](./references/bootstrap.md)
- [references/repo-discovery.md](./references/repo-discovery.md)
- [references/evaluation.md](./references/evaluation.md)
- [references/schema-overview.md](./references/schema-overview.md)

## 脚本列表

- `scripts/install_skill.py`
- `scripts/bootstrap_router.py`
- `scripts/resolve_entry.py`
- `scripts/rebuild_index.py`
- `scripts/check_reuse.py`
- `scripts/check_deps.py`
- `scripts/check_public_api.py`
- `scripts/check_index_freshness.py`
- `scripts/check_bundle_governance.py`
- `scripts/run_evaluation.py`
- `scripts/sync_feedback.py`
- `scripts/validate_router_bundle.py`

## CI

GitHub Actions workflow 位于 [.github/workflows/ci.yml](./.github/workflows/ci.yml)，会执行：

- 安装依赖。
- 校验 skill 结构。
- 运行单元测试。
- bootstrap 自仓库 bundle。
- validate bundle。
- governance audit。
- freshness check。
- route evaluation。

## 边界与风险

需要明确：

- 首次 bootstrap 只是 first pass。
- 没有 profile 时，结果会偏保守。
- generated-only evaluation 只能说明系统自洽，不代表架构成熟。
- `review_required=true` 或 `forbidden_write_paths=["**"]` 时，agent 不应自动写产品代码；可以做只读分析、补证据、修 profile 建议或请求 scoped override。
- `decision_confidence=high` 不代表可以写；它可能代表“很确定应该停”。
- `action` 是建议动作，不是最终工程命令；写入边界、veto、owner、canonical root 和生命周期约束优先级更高。
- 生命周期操作，例如 delete、merge、deprecate、replace、migrate，必须 review-first。
- 这个 skill 给方向、证据和约束，最终实现方案仍应来自真实代码分析、测试和用户确认。

## 许可证

见 [LICENSE](./LICENSE)。
