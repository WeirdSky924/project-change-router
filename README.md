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
- 对重复实现、错误边界、public API 绕过、反向依赖和 runtime cycle 做 guardrail 检查；TypeScript type-only edge 不会被误算成 runtime edge。
- 用 commit、内容结构摘要、索引路径、stale entry 和实际 changed paths 校验 freshness。
- 用 exact baseline 阻止中央文件、800/1200 行文件、禁用实现根和第二 canonical owner 的新增净增长。
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

安装器使用 staging、完整载荷递归哈希、递归 Python 编译、治理 API probe 和原子替换。只有新副本完整通过校验后才替换旧 skill；失败时会恢复旧安装，避免顶层脚本、`router_support`、schemas 或文档出现跨版本混装。

源码 checkout 和安装目标必须是不同路径。如果当前 Git checkout 已位于 `~/.codex/skills/project-change-router`，不要用安装器覆盖它；需要同时安装两个目标时使用独立 checkout，或只安装另一个目标。`--verify-only` 必须读取 0.3 原子安装建立的可信 manifest；没有该 manifest 的旧副本需要先原子重装一次，之后哈希验证才有来源完整性意义。

## 从旧版安全升级

全局 skill 和项目 bundle 是两个独立层次：

- 全局 skill 位于 `~/.codex/skills/project-change-router` 或 `~/.claude/skills/project-change-router`，保存脚本和工作流。
- 项目 bundle 位于 `<repo-root>/project-change-router/`，保存该项目长期校准的 capability、owner、path map、feedback 和 evaluation 数据。

更新全局 skill 不需要、也不应该自动重建项目 bundle。安全升级步骤如下：

1. 在本 skill 源码仓库更新到准备使用的版本。
2. 运行原子安装命令：

```powershell
python scripts/install_skill.py --target both --inject-hints
```

3. 验证 Codex 和 Claude Code 安装副本的文件哈希及复用扫描 API：

```powershell
python scripts/install_skill.py --target both --verify-only
```

4. 对一个已经长期使用 PCR 的项目，只做只读兼容检查：

```powershell
python <new-skill-root>\scripts\validate_router_bundle.py --repo <existing-repo> --format json
python <new-skill-root>\scripts\check_bundle_governance.py --repo <existing-repo> --format json
python <new-skill-root>\scripts\check_index_freshness.py --repo <existing-repo> --changed-path <known-path> --comparison-commit <trusted-base-commit> --format json
python <new-skill-root>\scripts\check_deps.py --repo <existing-repo> --comparison-commit <trusted-base-commit> --format json
python <new-skill-root>\scripts\check_public_api.py --repo <existing-repo> --comparison-commit <trusted-base-commit> --format json
python <new-skill-root>\scripts\check_structure.py --repo <existing-repo> --comparison-commit <trusted-base-commit> --format json
python <new-skill-root>\scripts\run_evaluation.py --repo <existing-repo> --format json
python <new-skill-root>\scripts\check_reuse.py --repo <existing-repo> --changed-path <known-path> --strict-completeness --format json
```

5. 验证通过后直接继续使用原 bundle。不要仅仅因为升级 skill 就运行 `bootstrap_router.py` 或 `rebuild_index.py`。

兼容保证：

- 新版本继续读取 schema v1 bundle。
- 0.3 新增架构治理 API v1，同时保持 reuse engine API v2。
- schema v1 的新增 evaluation 字段保持 optional；runtime 使用安全默认值且不写回旧 YAML，缺少或显式关闭 evaluation enforcement 都保持 `review_only`，不能授予写入权限。
- `normal` 只接受至少 30 个带 `curated_case_ids` 的真实案例、完整六类校准矩阵、明确 capability 期望以及合法 attestation；阈值只能收紧，生成案例和缺少 provenance 的旧案例始终保持 `review_only`。
- 旧 bundle 没有 `reuse_scan_scope`、`reuse_scan_runtime` 或 `reuse_scan_retention` 时，代码使用新默认值，但不会写回或改动 YAML。
- 新 fingerprint、checkpoint、canonical 和 diagnostic 默认写到用户缓存目录，不写入目标仓库，也不要求修改目标仓库 `.gitignore`。
- 安装器不会搜索任何项目目录，不会修改已有 profile、manual feedback、evaluation case、owner 或 lifecycle 数据。
- 旧 bundle 中错误的仓库级 `** -> concrete capability` 映射，在存在更具体映射时不会扩大 reuse 扫描范围；治理审计仍会提示修正元数据。
- “旧 bundle 可读”不表示历史报告永远满足新版输出 schema；需要作为当前样例或 CI fixture 使用的报告应按当前报告契约重新生成。

只有在项目结构、owner、public entry 或 capability 边界确实发生变化时才执行 rebuild。执行前应先把直接写在生成 YAML 中的人工真值迁移到 `.project-change-router.yaml`，并保留 manual feedback、curated evaluation 和 lifecycle 数据。可使用 [旧 bundle 更新提示词](./examples/agent-workflows/update-existing-router-bundle-prompt.md) 让 agent 做这次受控刷新。

安装器成功输出中的：

```text
repository_bundles_modified=0
```

表示本次升级没有触碰任何项目内 bundle。

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
python scripts/rebuild_index.py --repo . --format json
python scripts/validate_router_bundle.py --repo . --format json
python scripts/check_bundle_governance.py --repo . --format json
python scripts/check_index_freshness.py --repo . --format json
python scripts/check_deps.py --repo . --format json
python scripts/check_public_api.py --repo . --format json
python scripts/check_structure.py --repo . --format json
python scripts/run_evaluation.py --repo . --format json
python scripts/check_reuse.py --repo . --changed-path scripts/router_support/owner_identity.py --strict-completeness --format json
python scripts/install_skill.py --target codex --codex-home <temporary-codex-home>
python scripts/install_skill.py --target codex --codex-home <temporary-codex-home> --verify-only
```

全新 bootstrap 会有意让 PCR 保持 `review_only`，直到 evaluation set 具备足量真实案例、完整校准矩阵和当前 attestation。因此在这条 smoke 流程中，`run_evaluation.py` 会以退出码 `1` 返回 `status=fail`、`enforcement_mode=review_only` 和 `evaluation_cases_not_curated` 原因。CI 会显式断言这一安全结果，而不是降低阈值，或把生成的种子案例冒充生产校准证据。

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

这些名称按 canonical、legacy、skill fallback 的优先级选择，不会合并。同一优先级只能存在一份；`.yaml` 与 `.yml` 并存会 fail-closed，必须先确定唯一真值源。

profile 可声明：

- capability 到路径的映射
- ownership rules
- 显式 capability ownership，包括一个真实 primary owner 和不同的 reviewers
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

Run dependency, public API, structure, freshness, evaluation, and strict-completeness reuse checks when their routed boundary is affected. Static checks supplement rather than replace logic, data, integration, and customer-flow verification.

If evaluation is below threshold or its attestation is missing/stale, keep PCR review-only even when the capability match itself looks correct.

When running check_reuse, inspect result_status, completion_status, evidence_complete, and summary.scan.scope together. Only completion_status=complete with evidence_complete=true closes the duplicate check for that capability scope. A bounded, incomplete, timeout, cancelled, or error result requires targeted source analysis and must not be reported as proof that no duplicate implementation exists.
```

更完整的可复制版本见 [examples/agent-workflows/unattended-plan-prompt.md](./examples/agent-workflows/unattended-plan-prompt.md)。

升级 skill 后不需要自动刷新旧 bundle。只有只读兼容检查证明索引确实陈旧，或者仓库边界已经变化时，才使用 [examples/agent-workflows/update-existing-router-bundle-prompt.md](./examples/agent-workflows/update-existing-router-bundle-prompt.md) 做受控刷新；该流程必须保留人工 profile、反馈、评估样例和生命周期信息。

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
| 检查中央增长、文件规模和唯一 owner | `python scripts/check_structure.py --repo <repo-root> --format json` |
| 检查索引新鲜度 | `python scripts/check_index_freshness.py --repo <repo-root> --format json` |
| 路由治理健康检查 | `python scripts/check_bundle_governance.py --repo <repo-root> --format json` |
| 路由质量回归评估 | `python scripts/run_evaluation.py --repo <repo-root> --format json` |
| 人工反馈回写 | `python scripts/sync_feedback.py --repo <repo-root> --feedback-file feedback.json --format json` |

## 架构治理

PCR 0.3 把原先容易依赖人工审查的结构约束变成可回归的通用 guardrail：

- Python 和 TypeScript/JavaScript import graph 区分 runtime 与 type-only edge，并报告 runtime cycle、解析诊断和依赖方向。
- `architecture_baseline` 只登记精确旧债；已登记问题可以告警，新问题或净增长失败。它不是 wildcard 豁免。
- `central_growth_baseline` 阻止 composition root、global gateway、顶层 controller 等中央 owner 继续吸收领域实现。
- `forbidden_implementation_roots` 阻止在 legacy、compat、generated 或非 canonical 根新增正式实现。
- `exclusive_source_owners` 阻止 profile 明确声明的受保护实现 token 出现在 canonical owner 之外；不同标识符的 raw transport、cache/store 或 DTO 重复仍需项目级 import、identifier 或 AST 门。
- `generated_output_baseline` 仅用于 canonical profile 迁移期的七个固定 PCR reference 产物，并绑定仓库唯一启用的 `.project-change-router.yaml` 或 `.project-change-router.yml`。规则源和每个非空 artifact provenance 都必须是该仓库对象格式的完整不可变 SHA；artifact 可以早于规则源，但必须是规则源与当前 rebuild source 的祖先，`null` 模式必须保持 `null`。固定摘要只投影掉顶层 `generated_at`、`source_commit` 和 capability catalog 中明确列出的 generator clock。`path_to_capability_map.path_index[*].code_file_count` 不从固定摘要中移除；它只在相同 `path_pattern` 且新旧值均为合法非负整数时作为 comparison-only rebuild volatile，以免仓库代码文件数量的正常变化造成假阳性。实际 pinned count 仍受摘要、canonical UTF-8 字节和行数约束，缺失、类型漂移或产物篡改仍会失败。普通 `rebuild_index.py` 验证成功后保留七个 tracked refs，只刷新 `router-config.yaml`、schemas 和 `latest.json`；失败时不写任何 bundle/report。evaluation attestation 会针对实际持久化的“新 config + pinned refs”重算。首次建立 pin 必须向 `check_structure.py` 或 `rebuild_index.py` 传入 `--initialize-generated-output-baseline <fingerprint>`；profile 文字不能自行授权。pin 启用、格式错误或尚未提交移除时，`bootstrap_router.py` 禁止清空正式 refs。
- stable capability 必须有唯一 `capability_ownership` 记录、真实 primary owner、不同 reviewer、lifecycle、contract/test binding 和 evaluation 覆盖；自动生成的 owner 标签、`UNKNOWN`、unassigned、缺失、重复或 provisional owner 都不提供自动写入授权。
- freshness 同时校验 commit、内容结构摘要、stale entries、索引路径、报告字段形状和 changed-path coverage。canonical config、七个 refs 与 schemas 即使被 bundle `ignore_paths` 命中也必须进入摘要，只有自引用的 `latest.json` 例外；显式 `--changed-path` 始终与真实 staged、unstaged、untracked、deleted 路径取并集；历史 source 只在其为当前 HEAD 祖先且快照、状态与诊断全部精确一致时通过。
- evaluation attestation 或阈值不满足时保持 `review_only`，不能因为 capability 命中正确就假定 action 和写入授权也可靠。

现有债务应先建立精确 baseline 来阻止新增，再由后续治理包持续降低 baseline；不能通过扩大 ignore、弱化规则或伪造 evaluation case 获得通过。字段、退出条件和 CI 组合见 [references/architecture-governance.md](./references/architecture-governance.md)。

## Reuse 扫描运行时

`check_reuse.py` 现在是 capability-scoped 的有界扫描器，不是全仓语义搜索器。一次 changed-path 检查按下面的顺序执行：

```text
changed paths
  -> path map / owner / key files / related tests / test bindings
  -> primary + dependency capability scope
  -> native fingerprint 候选召回
  -> 文件对去重与 Top-K
  -> 隔离 worker 精确比较
  -> canonical / checkpoint / diagnostic 报告
```

关键行为：

- changed path 即使不在 `modules[].path` 中，只要它是 key file、index source、related test、test binding 或精确 path-map 项，也会直接进入候选集。
- 无法解析 capability 时返回 `completion_status=incomplete`，不会静默回退全仓扫描。
- 有具体 path mapping 时，旧 bundle 中的仓库级 `** -> concrete capability` 不参与扩展范围。
- 精确 path-map owner 优先于宽 module owner；只有同一精确路径显式声明 shared owner 时才保留第二 owner。
- dependency scope 只沿已解析的 runtime import edge 双向扩张一跳；TypeScript type-only edge 和传递依赖不会扩张扫描范围。
- import parser/resolver diagnostic 会令 evidence incomplete，不会被当成干净依赖图。
- test path 优先使用同 capability 的 related tests、test bindings 和 owner surface，不默认比较所有产品模块。
- 相同文件对只计算一次；多个 capability 命中同一重复对时合并 capability 列表和最高严重度。
- 超过全文比较大小限制但 fingerprint 高度相似的文件会输出 P2 `duplicate-fingerprint-candidate`，要求 agent 做定向源码分析；它不是精确重复结论。

### Fingerprint 缓存

缓存使用 Python 原生 `sqlite3` 和 `hashlib`，保存文件身份、大小、归一化长度、token sketch、内容摘要和算法版本，不保存完整归一化源码。第二次扫描可直接复用未变化 owner 文件的 fingerprint，只对 Top-K 精确候选读取全文。

默认运行时目录不在项目仓库中：

- Windows：`%LOCALAPPDATA%\project-change-router\repositories\<repo-key>\`
- Linux/macOS：`$XDG_CACHE_HOME/project-change-router/repositories/<repo-key>/`，未设置时使用 `~/.cache/...`

缓存模式：`auto`、`read-only`、`off`、`rebuild`。可通过 `--cache-mode` 或 profile/change-rules 配置。

### Timeout 与取消

CLI 在隔离子进程中运行扫描：

- soft timeout 停止派发新比较并写 checkpoint。
- hard timeout 终止仍卡在单次全文相似度计算中的 worker。
- `Ctrl+C` 走相同的取消、终止和 canonical 报告收口流程。
- hard timeout 至少比 soft timeout 多一秒，确保有收口窗口。

命令行覆盖优先级高于 profile/change-rules：

```powershell
python scripts/check_reuse.py --repo <repo-root> --changed-path <path> `
  --timeout-seconds 60 --hard-timeout-seconds 75 `
  --cache-mode auto --diagnostics auto --format json
```

数量预算仍可使用：`--max-candidate-files`、`--max-owner-files`、`--max-comparisons`、`--max-file-bytes`、`--top-k-owner-files`。

### 报告分级

- `canonical`：agent/CI 使用的最终机器契约；完成、受预算限制、超时、取消和错误都会生成。
- `checkpoint`：可恢复的过程状态；完整完成后删除，非完整扫描短期保留，不能作为最终结论。
- `diagnostic`：scope、缓存命中、阶段耗时和淘汰原因；`auto` 只为慢扫描或非完整扫描保留。

必须同时读取：

```text
result_status      = pass | warn | fail
completion_status  = complete | bounded | incomplete | timeout | cancelled | error
evidence_complete  = true | false
```

典型含义：

| 场景 | result_status | completion_status |
| --- | --- | --- |
| 已完成目标 scope，未发现阻断 | `pass` | `complete` |
| 已完成目标 scope，发现 P1 重复 | `fail` | `complete` |
| 没有 P0/P1，但达到预算或大文件限制 | `warn` | `bounded` |
| changed path 无法完整归属 | `warn` | `incomplete` |
| worker 超过截止时间 | `warn` | `timeout` |
| 取消前已经发现 P1 | `fail` | `cancelled` |

只有 `completion_status=complete` 且 `evidence_complete=true` 才能说明“已完成目标 capability scope 的重复检查”。这仍不代表扫描了无关 capability，也不替代 agent 对候选文件的源码分析。

### 自动保留与清理

canonical 结果按输入、scope、证据、预算和 findings 做语义去重；P0/P1 报告自动 pin。默认保留 90 天/500 个 canonical、7 天 checkpoint、3 天/200 个 diagnostic，fingerprint 最多 50000 条，单仓运行时上限 512 MiB。

清理只删除 SQLite manifest 登记且位于解析后 runtime root 内的文件，不会 glob 删除仓库内容。可单独运行：

```powershell
python scripts/check_reuse.py --repo <repo-root> --cleanup-only --format json
```

默认退出码兼容旧自动化：无 P0/P1 时仍为 `0`；P0/P1 为 `1`；timeout/error 为 `2`；取消为 `130`。使用 `--strict-completeness` 时，`bounded` 和 `incomplete` 也返回 `2`。自动化应优先读取 JSON 字段，不要只看退出码。

完整配置与行为契约见 [references/reuse-scan-runtime.md](./references/reuse-scan-runtime.md)。

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
- stable capability 是否具备非 provisional owner、reviewer、lifecycle、正例与边界 evaluation 覆盖。

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
- [examples/profiles/reuse-runtime.project-change-router.yaml](./examples/profiles/reuse-runtime.project-change-router.yaml)

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
- [examples/outputs/check-structure.pass.json](./examples/outputs/check-structure.pass.json)
- [examples/outputs/check-reuse.pass.json](./examples/outputs/check-reuse.pass.json)
- [examples/outputs/check-reuse.warn.json](./examples/outputs/check-reuse.warn.json)
- [examples/outputs/check-reuse.timeout.json](./examples/outputs/check-reuse.timeout.json)
- [examples/outputs/check-bundle-governance.warn.json](./examples/outputs/check-bundle-governance.warn.json)
- [examples/outputs/run-evaluation.pass.json](./examples/outputs/run-evaluation.pass.json)

参考文档：

- [references/router-workflow.md](./references/router-workflow.md)
- [references/governance-outputs.md](./references/governance-outputs.md)
- [references/bootstrap.md](./references/bootstrap.md)
- [references/repo-discovery.md](./references/repo-discovery.md)
- [references/evaluation.md](./references/evaluation.md)
- [references/schema-overview.md](./references/schema-overview.md)
- [references/architecture-governance.md](./references/architecture-governance.md)
- [references/reuse-scan-runtime.md](./references/reuse-scan-runtime.md)

## 脚本列表

- `scripts/install_skill.py`
- `scripts/bootstrap_router.py`
- `scripts/resolve_entry.py`
- `scripts/rebuild_index.py`
- `scripts/check_reuse.py`
- `scripts/reuse_runtime.py`
- `scripts/check_deps.py`
- `scripts/check_public_api.py`
- `scripts/check_structure.py`
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
- dependency direction、runtime cycle 与 public API check。
- central growth、800/1200 文件规模、forbidden root 与 exclusive owner structure check。
- route evaluation。
- capability-scoped reuse scan、隔离 worker 和严格完整性检查。
- 临时目录中的原子安装与 `--verify-only` 完整载荷校验。

## 边界与风险

需要明确：

- 首次 bootstrap 只是 first pass。
- 没有 profile 时，结果会偏保守。
- generated-only evaluation 只能说明系统自洽，不代表架构成熟。
- capability 命中正确不代表 action、secondary contract 或写入授权可靠；evaluation 未达阈值时仍为 `review_only`。
- `review_required=true` 或 `forbidden_write_paths=["**"]` 时，agent 不应自动写产品代码；可以做只读分析、补证据、修 profile 建议或请求 scoped override。
- `decision_confidence=high` 不代表可以写；它可能代表“很确定应该停”。
- `action` 是建议动作，不是最终工程命令；写入边界、veto、owner、canonical root 和生命周期约束优先级更高。
- `check_reuse` 的 `result_status=pass` 只有在 `completion_status=complete` 且 `evidence_complete=true` 时才表示目标 scope 已完成；bounded、timeout 和 incomplete 只能作为定向分析证据。
- 生命周期操作，例如 delete、merge、deprecate、replace、migrate，必须 review-first。
- 这个 skill 给方向、证据和约束，最终实现方案仍应来自真实代码分析、测试和用户确认。

## 许可证

见 [LICENSE](./LICENSE)。
