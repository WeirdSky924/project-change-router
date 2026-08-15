# Project Change Router Skill

中文默认版。英文版见 [README.en.md](./README.en.md)。

`project-change-router` 是一个面向大型仓库的 AI coding skill，可用于 Codex、Claude Code 和 DeepSeek Harness。它的目标不是让 agent 更大胆地猜架构，而是让 agent 更少乱猜：在真正修改代码之前，先用仓库本地的路由 bundle 获取能力归属、canonical root、owner、读写边界、复用风险和处理倾向。

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

- 少乱猜优先于更聪明地猜。证据不足时宁可保留 `unknown` 并让 `execution_gate=blocked`，不要伪装成确定结论。
- profile 优先于纯启发式。真实 owner、public entry、capability 边界和 path pattern 应逐步写入 `.project-change-router.yaml`。
- 结构证据优先于名字相似。路径、owner、public API、依赖关系、测试绑定比语义相似更可靠。
- 早期仓库默认保守。`seed` / `emerging` 阶段不应轻易自动 `extend` 或 `extract`。
- `review` 不是失败，也不是写入门禁；它是 action 建议层的调查方向。真正决定当前是否可写的是 `execution_gate`。
- 路由输出是一体化契约。`execution_gate`、安全信封和 typed findings 必须遵守，`action` 和解阻建议用于辅助判断，不能替代源码分析。
- 结果必须能持续变准。人工 override、误判、profile 修正和真实案例应沉淀到 feedback 与 evaluation。

## 两层使用模型

PCR 的输出分为两层，使用时不要混在一起理解。

必须执行层：

- 必须先读 `execution_gate.state`：`pass`、`conditional`、`blocked` 是唯一权威写入状态。
- 必须尊重 `allowed_write_paths`、`forbidden_write_paths` 和 `must_read_before_edit`。
- 必须识别并保护已有 owner、public entry、canonical root 和依赖方向。
- 不能在已有能力可能存在时新建第二套平行实现中心。
- `blocked` 时禁止产品代码写入；`conditional` 时必须先执行 `required_commands` 并限制在给定 envelope；`pass` 也不能越过 envelope。
- `veto_reasons`、unknown evidence、生命周期、高风险重叠和 provisional 边界必须追溯到 typed finding 与 policy rule，不能忽略或仅凭 action 覆盖。

参考建议层：

- `action` 是当前证据下的处理倾向，不是最终工程命令。
- `recommended_next_steps`、`safe_next_steps`、`analysis_directions`、`why_not_actions` 和 `profile_repair_hints` 是解阻方向和调查提示。
- `action=review` 不等于永远不能做，也不自动等于 blocked；它表示应优先补证据、补 profile、读源码或协调确认，最终仍以 `execution_gate` 为准。
- 最终实现方案仍必须来自真实源码分析、依赖追踪、测试和用户确认。

## 能力范围

这个 skill 可以：

- 为目标仓库生成本地 `project-change-router/` bundle。
- 识别仓库模块、capability、owner、public entry、路径归属和依赖方向。
- 根据请求和 changed paths 输出 route report，包含强约束和建议动作。
- 用统一 `run_change_flow.py` 编排 route、freshness、dependency、public API、structure、governance 和 reuse 检查，默认只返回 compact 安全信封并把完整证据保存为内容寻址 artifact。
- 把所有门禁证据规范化为可追溯 typed findings，并以单一版本化规则表确定 `execution_gate`。
- 基于 changed-path 的正反向依赖闭包增量复用可信全局快照，而不是停止全局不变量检查。
- 将 reuse 拆为 capability 内、跨 capability 和 new/extract/lifecycle 扩展扫描三条独立覆盖通道。
- 对重复实现、错误边界、public API 绕过、反向依赖和 runtime cycle 做 guardrail 检查；TypeScript type-only edge 不会被误算成 runtime edge。
- 用 commit、内容结构摘要、索引路径、stale entry 和实际 changed paths 校验 freshness。
- 用 exact baseline 阻止中央文件、800/1200 行文件、禁用实现根和第二 canonical owner 的新增净增长。
- 通过 `path-to-capability-map.yaml` 暴露路径归属、共享归属和未覆盖模块。
- 用 schema 校验 bundle 与报告。
- 用 evaluation set 检查路由质量是否退化。
- 用 governance audit 检查 profile/catalog 同步、ownership 颗粒度、contract 质量、forbidden density、evaluation 覆盖和 capability 生命周期。
- 在 Codex / Claude Code 安装时追加提示块，并通过 DeepSeek Harness skill catalog 暴露触发描述，让 agent 更容易在功能级 create / modify / delete 前主动触发该 skill。

它不应该：

- 替代详细代码阅读、依赖追踪、测试设计和架构分析。
- 把 `action` 当成无需分析即可执行的最终命令。
- 把 `action=review` 本身当作放行或阻塞依据；写入状态必须读取 `execution_gate`。
- 把 generated-only bundle 当作成熟架构事实。
- 因为名字相似就强行复用或扩展已有 capability。
- 在没有确认 canonical root 时创建第二套实现中心。

## 路由动作

`resolve_entry.py` 会输出五类动作。这些动作是处理建议和调查方向，不是最终架构命令：

- `reuse`：使用已有 capability，不修改核心实现。
- `extend`：在已有共享 capability 或兼容扩展点上增加行为。
- `extract`：先把重复逻辑抽到共享 capability，再让调用方复用。
- `new`：没有合适复用目标，应建立新的隔离 capability 边界。
- `review`：优先补证据、补 profile、做跨能力协调或请求人工确认；它描述调查方向，不授予也不撤销写权限。

`review` 需要特别理解：它不是“系统没用”，也不是永久阻塞，更不是门禁状态。在空仓或早期仓里，可能出现：

```json
{
  "action": "review",
  "routing_confidence": 0.0,
  "routing_confidence_level": "low",
  "decision_confidence": 0.95,
  "decision_confidence_level": "high"
}
```

这表示：系统对“应该落到哪个 capability”没有把握，但对当前 action 建议很有把握。是否可以写产品代码必须另读 `execution_gate.state`；例如相关路径未索引时会是 `blocked`，而只有无关且不扩大的可信历史债务时可为 `conditional`。

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
- `authorization_context`
- `route_fingerprint`
- `runtime_identity`
- `typed_findings`
- `execution_gate`
- `gate_shadow`
- `must_read_targets`
- `inventory_targets`
- `unresolved_read_targets`
- `authorization_request`

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

### 0.4 执行门禁与证据模型

PCR 0.4 把“路由建议”和“是否可写”彻底拆开：

| 字段 | 作用 |
| --- | --- |
| `action` | `reuse / extend / extract / new / review`，只提供工程调查与处理方向 |
| `execution_gate.state=pass` | 相关证据完整且没有任务相关阻塞项；仍须遵守读写 envelope |
| `execution_gate.state=conditional` | 只剩已证明无关或不扩大的可信历史债务；必须执行前置命令并保持有界写入 |
| `execution_gate.state=blocked` | 存在 unknown/incomplete、任务相关 P0/P1、owner/canonical/public API/lifecycle/高风险问题或硬不变量冲突 |

门禁不重新扫描仓库，也不做第二套路由推理。所有结果都由一个版本化 policy table 对 schema-valid typed findings 做确定性归约。每条 finding 包含稳定 `finding_id`、来源、严重级、全局/闭包/局部不变量分类、delta、task relevance、evidence status、policy rule、路径/能力、相关性链路与证据摘要。

`gate_shadow` 仅保留旧门禁与新门禁的对照诊断；0.4 中 `execution_gate.authoritative=true`，旧门禁不再决定写入。`output_complete=false` 或无法满足新版精度的 schema-v1 输入必须形成 unknown/incomplete finding 并阻塞，不能用乐观默认值补齐。

统一入口：

```powershell
python scripts/run_change_flow.py --repo <repo-root> --request "Add invoice refund support" --changed-path services/billing/refund.py --format compact-json
```

默认 compact 输出始终保留不可投影的安全信封：`execution_gate`、`veto_reasons`、`allowed_write_paths`、`forbidden_write_paths`、`unknown_evidence`、`artifact_path`、`artifact_digest`、`output_complete`。完整 route、checks、findings、cache/baseline 证据写入内容寻址 artifact；`--format full-json` 返回完整报告，`--format artifact-reference` 返回最小引用，`--field` 只能增加普通字段，`--exclude-field` 不能隐藏安全字段。

## 安装

Python 要求：

- Python `>= 3.10`
- DeepSeek Harness 插件验证遵循 Harness 当前 Node 要求：`^22.19.0 || >=24.0.0`；仅安装 filesystem skill 不额外启动 Node 进程

安装依赖：

```powershell
pip install -r requirements.txt
```

或以开发模式安装：

```powershell
pip install -e .[dev]
```

同时安装到 Codex、Claude Code 和 DeepSeek Harness：

```powershell
python scripts/install_skill.py --target all --inject-hints
```

安装路径：

- Codex：`%USERPROFILE%\.codex\skills\project-change-router`
- Claude Code：`%USERPROFILE%\.claude\skills\project-change-router`
- DeepSeek Harness：`$DSH_HOME/skills/project-change-router`；没有设置 `DSH_HOME` 时默认 `~/.dsh/skills/project-change-router`

`--inject-hints` 只为需要规则入口提示的 Codex 和 Claude Code 追加标记块，不会重写整个文件：

- Codex：追加到 `~/.codex/AGENTS.md`
- Claude Code：追加到 `~/.claude/CLAUDE.md`

这是一种“伪强制”提醒，用于让 agent 在功能级 create / modify / delete 前主动触发 skill。它不是后台守护进程，也不会绕过对话触发机制。

DeepSeek Harness 通过 skill catalog 的 `name` 和 `description` 自动向模型暴露 PCR，并支持在用户消息中用 `/project-change-router` 显式触发，因此不需要修改 Harness 的全局提示文档。

兼容说明：`--target both` 继续保持旧语义，只安装 Codex 和 Claude Code；`--target deepseek` 只安装 Harness；`--target all` 安装三端。项目级 Harness 安装可以把 `.dsh` 目录作为 home：

```powershell
python scripts/install_skill.py --target deepseek --dsh-home <repo-root>/.dsh
```

Harness 原生 filesystem provider 会发现 `<repo-root>/.dsh/skills/project-change-router/SKILL.md`。它也兼容 `<repo-root>/.agents/skills`、`~/.agents/skills` 和自定义 skill roots，但本安装器默认写入官方 `DSH_HOME` 路径。

### 作为 DeepSeek Harness GitHub 插件安装

仓库根 `package.json` 声明了 `dsh.bundle`，其 Cordis provider 从根 `SKILL.md` 读取同一份 skill 内容和资源目录，不维护第二套提示词。建议固定提交 SHA 安装：

```powershell
dsh plugin --profile <profile-name> add github:WeirdSky924/project-change-router-skill#<commit-sha>
dsh --profile <profile-name> --dump-config
```

这个 bundle 使用原生 ESM，没有 TypeScript 构建、`prepare` 脚本或安装期代码执行许可。项目级 `.dsh/skills` 和用户级 filesystem skill 的 rank 高于 bundled provider，因此可按 Harness 官方优先级覆盖插件版本。

卸载 profile 插件：

```powershell
dsh plugin --profile <profile-name> remove project-change-router-skill
```

Harness 官方社区发现以公开 GitHub 仓库的 `dsh-plugin` topic 为入口；发布前应为仓库设置 `dsh-plugin`、`deepseek-harness`、`agent-skills` 和 `coding-agent` 等检索 topic。DeepSeek Harness 当前仍是 developer preview，升级 Harness preview 版本后应重新运行本仓库的 provider smoke 和安装验证。

安装器使用 staging、完整载荷递归哈希、递归 Python 编译、治理 API probe 和原子替换。只有新副本完整通过校验后才替换旧 skill；失败时会恢复旧安装，避免顶层脚本、`router_support`、schemas、文档或 DSH provider 出现跨版本混装。

源码 checkout 和安装目标必须是不同路径。如果当前 Git checkout 已位于任一目标的 `skills/project-change-router`，不要用安装器覆盖它；需要同时安装多个目标时使用独立 checkout，或只安装其他目标。`--verify-only` 必须读取原子安装建立的可信 manifest；没有该 manifest 的旧副本需要先原子重装一次，之后哈希验证才有来源完整性意义。

## 从旧版安全升级

全局 skill 和项目 bundle 是两个独立层次：

- 全局 skill 位于 `~/.codex/skills/project-change-router`、`~/.claude/skills/project-change-router` 或 `~/.dsh/skills/project-change-router`，保存脚本和工作流。
- 项目 bundle 位于 `<repo-root>/project-change-router/`，保存该项目长期校准的 capability、owner、path map、feedback 和 evaluation 数据。

更新全局 skill 不需要、也不应该自动重建项目 bundle。安全升级步骤如下：

1. 在本 skill 源码仓库更新到准备使用的版本。
2. 运行原子安装命令：

```powershell
python scripts/install_skill.py --target all --inject-hints
```

3. 验证 Codex、Claude Code 和 DeepSeek Harness 安装副本的文件哈希及复用扫描 API：

```powershell
python scripts/install_skill.py --target all --verify-only
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
python <new-skill-root>\scripts\run_change_flow.py --repo <existing-repo> --request "Compatibility check only" --changed-path <known-path> --format compact-json
```

5. 验证通过后直接继续使用原 bundle。不要仅仅因为升级 skill 就运行 `bootstrap_router.py` 或 `rebuild_index.py`。

兼容保证：

- 新版本继续读取 schema v1 bundle。
- 0.4 使用架构治理 API v2、typed finding / gate / change flow / authorization API v1，并保持 reuse engine API v2。
- 所有新版报告带统一 `runtime_identity`，绑定 skill version、Git commit（可用时）、安装载荷摘要、schema/API/policy/parser 版本。缓存、baseline、finding、授权与 artifact 都绑定该身份。
- schema v1 的新增 evaluation 字段保持 optional；runtime 使用安全默认值且不写回旧 YAML，缺少或显式关闭 evaluation enforcement 都保持 `review_only`，不能授予写入权限。
- schema v1 无法提供 typed finding、relevance closure 或 trusted baseline 所需精度时，0.4 输出 `unknown` 并让 execution gate 保持 blocked；它不会伪造精确度，也不会把新字段写回旧 bundle。
- `normal` 只接受至少 30 个带 `curated_case_ids` 的真实案例、完整六类校准矩阵、明确 capability 期望以及合法 attestation；阈值只能收紧，生成案例和缺少 provenance 的旧案例始终保持 `review_only`。
- 旧 bundle 没有 `reuse_scan_scope`、`reuse_scan_runtime` 或 `reuse_scan_retention` 时，代码使用新默认值，但不会写回或改动 YAML。
- 新 fingerprint、checkpoint、canonical、diagnostic、flow artifact、baseline 和 authorization manifest 默认写到用户缓存目录，不写入目标仓库，也不要求修改目标仓库 `.gitignore`。
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

DeepSeek Harness 中也使用 whitespace-bounded slash invocation；或者让模型根据 skill catalog 的描述主动加载：

```text
/project-change-router resolve the correct capability entry for this change
```

推荐用统一 flow 解析并检查一次变更：

```powershell
python scripts/run_change_flow.py --repo <repo-root> --request "Add invoice refund support" --changed-path services/billing/refund.py --format compact-json
```

也可以从请求文件读取；需要单独排查路由时仍可使用兼容的 `resolve_entry.py`：

```powershell
python scripts/run_change_flow.py --repo <repo-root> --request-file request.md --changed-path services/billing/refund.py --format artifact-reference --output flow-report.json
python scripts/resolve_entry.py --repo <repo-root> --request-file request.md --changed-path services/billing/refund.py --format json --output route-report.json
```

解析后执行规则：

- 如果 `execution_gate.state=blocked`：禁止产品代码写入；按 decisive finding、unknown evidence 和 required commands 补证据或进入有来源的授权流程。
- 如果 `execution_gate.state=conditional`：先执行全部 required commands，只在返回的 allowed paths 内写入；它只适用于已证明无关或不扩大的可信历史债务。
- 如果 `execution_gate.state=pass`：完成精确 must-read 后在 envelope 内推进。
- `action=review` 只表示优先调查、补 profile 或协调，不自行阻塞；下面所有 action 也都不能覆盖 gate。
- 如果 `action=reuse`：把它当成复用倾向；优先读取 `must_read_before_edit` 和 `required_reads`，不要改核心实现。
- 如果 `action=extend`：把它当成扩展倾向；只在 `allowed_write_paths` 内扩展，避免绕过 public entry。
- 如果 `action=extract`：把它当成抽取倾向；先确认重复面、调用方和测试，再抽共享能力。
- 如果 `action=new`：把它当成新边界倾向；先命名隔离边界，不要在已有 capability 旁边生成第二套平行中心。

## Codex / Claude Code / DeepSeek Harness 提示词

建议在无人值守计划或长期任务中加入：

```text
Before any feature-level create, modify, delete, merge, deprecate, or migration work, invoke project-change-router and run run_change_flow.py for the target repository. Use PCR as a direction index and guardrail system, not as an automatic architecture decision engine.

Read execution_gate before action. execution_gate.state is the authoritative write decision. For blocked, do not write product code. For conditional, run every required_command and keep writes inside the bounded envelope. For pass, still obey the envelope and precise must-read targets.

Treat action, including action=review, as advisory direction only. Use recommended_next_steps, safe_next_steps, analysis_directions, profile_repair_hints, and why_not_actions for source analysis and user-confirmed decisions; never turn action into a second gate.

Never ignore veto_reasons, unknown_evidence, canonical owner/root, public entry, lifecycle findings, duplicate risk, or unresolved closure evidence. Trace them to typed findings and policy rules. Bounded or incomplete evidence cannot prove absence.

Do not create a second implementation center when an existing capability or canonical root may exist. If routing evidence is weak, repair the profile or ask for confirmation instead of guessing.

Use must_read_targets by path, symbol, and content digest. Treat directories only as inventory_targets. Run unresolved_read_targets queries and keep the target unresolved until a unique implementation is proven.

For an override, create an authorization_request and require explicit user confirmation before creating a grant. Bind it to task, paths, owner, route, pre-change snapshot, mutation envelope, runtime/policy identity, expiry, and use count. Never revive a consumed or invalidated grant.

After routed changes, execute post_change_closeout, rerun the affected flow/checks, and record feedback/evaluation cases after review, override, lifecycle change, false route, or routing correction.

Keep full diagnostics in the content-addressed artifact. In the main context retain the compact safety envelope, decisive delta, exact reads, and next command. Never hide a safety-envelope field through projection.
```

更完整的可复制版本见 [examples/agent-workflows/unattended-plan-prompt.md](./examples/agent-workflows/unattended-plan-prompt.md)。

升级 skill 后不需要自动刷新旧 bundle。只有只读兼容检查证明索引确实陈旧，或者仓库边界已经变化时，才使用 [examples/agent-workflows/update-existing-router-bundle-prompt.md](./examples/agent-workflows/update-existing-router-bundle-prompt.md) 做受控刷新；该流程必须保留人工 profile、反馈、评估样例和生命周期信息。

## 生命周期命令表

| 场景 | 命令 |
| --- | --- |
| 初次接入仓库 | `python scripts/bootstrap_router.py --repo <repo-root> --format json` |
| 仓库结构大改后 | `python scripts/rebuild_index.py --repo <repo-root> --format json` |
| 统一路由、检查与收口计划 | `python scripts/run_change_flow.py --repo <repo-root> --request "<request>" --changed-path <path> --format compact-json` |
| 修改前解析路由 | `python scripts/resolve_entry.py --repo <repo-root> --request "<request>" --changed-path <path> --format json` |
| 创建/授予/消费授权 | `python scripts/manage_authorization.py --repo <repo-root> <request|grant|consume|inspect> ...` |
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

PCR 0.4 在原有可回归 guardrail 上增加 typed findings、增量全局证据、可信 baseline 和权威 execution gate：

- Python 和 TypeScript/JavaScript import graph 区分 runtime 与 type-only edge，并报告 runtime cycle、解析诊断和依赖方向。
- `architecture_baseline` 只登记精确旧债；已登记问题可以告警，新问题或净增长失败。它不是 wildcard 豁免。
- `central_growth_baseline` 阻止 composition root、global gateway、顶层 controller 等中央 owner 继续吸收领域实现。
- `forbidden_implementation_roots` 阻止在 legacy、compat、generated 或非 canonical 根新增正式实现。
- `exclusive_source_owners` 阻止 profile 明确声明的受保护实现 token 出现在 canonical owner 之外；不同标识符的 raw transport、cache/store 或 DTO 重复仍需项目级 import、identifier 或 AST 门。
- `generated_output_baseline` 仅用于 canonical profile 迁移期的七个固定 PCR reference 产物，并绑定仓库唯一启用的 `.project-change-router.yaml` 或 `.project-change-router.yml`。规则源和每个非空 artifact provenance 都必须是该仓库对象格式的完整不可变 SHA；artifact 可以早于规则源，但必须是规则源与当前 rebuild source 的祖先，`null` 模式必须保持 `null`。固定摘要只投影掉顶层 `generated_at`、`source_commit` 和 capability catalog 中明确列出的 generator clock。`path_to_capability_map.path_index[*].code_file_count` 不从固定摘要中移除；它只在相同 `path_pattern` 且新旧值均为合法非负整数时作为 comparison-only rebuild volatile，以免仓库代码文件数量的正常变化造成假阳性。实际 pinned count 仍受摘要、canonical UTF-8 字节和行数约束，缺失、类型漂移或产物篡改仍会失败。普通 `rebuild_index.py` 验证成功后保留七个 tracked refs，只刷新 `router-config.yaml`、schemas 和 `latest.json`；失败时不写任何 bundle/report。evaluation attestation 会针对实际持久化的“新 config + pinned refs”重算。首次建立 pin 必须向 `check_structure.py` 或 `rebuild_index.py` 传入 `--initialize-generated-output-baseline <fingerprint>`；profile 文字不能自行授权。pin 启用、格式错误或尚未提交移除时，`bootstrap_router.py` 禁止清空正式 refs。
- stable capability 必须有唯一 `capability_ownership` 记录、真实 primary owner、不同 reviewer、lifecycle、contract/test binding 和 evaluation 覆盖；自动生成的 owner 标签、`UNKNOWN`、unassigned、缺失、重复或 provisional owner 都不提供自动写入授权。
- freshness 同时校验 commit、内容结构摘要、stale entries、索引路径、报告字段形状和 changed-path coverage。全局报告继续暴露所有债务；route gate 再按当前 capability 的正反向依赖闭包把 delta 分为 `task_local_new`、`baseline_unchanged`、`unknown`。相关变化和无法证明无关的变化继续阻塞，已证明属于其他 capability 的不变旧债不会把局部安全变更改成全仓 `forbidden=["**"]`。canonical config、七个 refs 与 schemas 即使被 bundle `ignore_paths` 命中也必须进入摘要，只有自引用的 `latest.json` 例外；显式 `--changed-path` 始终与从索引 source 到 HEAD、staged、unstaged、untracked、deleted 的真实路径取并集。
- 每个 route report 都带 `authorization_context` 和 `route_fingerprint`，绑定源提交、结构摘要、路由真值、changed paths、capability、action、override 条件与读写 envelope。人工反馈必须回传原始 fingerprint；输入或报告改变后授权自动失效，manifest 不能自行恢复已消费授权。
- evaluation attestation 或阈值不满足时保持 `review_only`，不能因为 capability 命中正确就假定 action 和写入授权也可靠。

现有债务应先建立精确 baseline 来阻止新增，再由后续治理包持续降低 baseline；不能通过扩大 ignore、弱化规则或伪造 evaluation case 获得通过。字段、退出条件和 CI 组合见 [references/architecture-governance.md](./references/architecture-governance.md)。

flow 中的 evidence baseline 还有更严格的来源约束：首次扫描、脏工作树、bounded/incomplete 结果只能成为 `candidate_snapshot` 或 `unknown`。只有干净 commit 上的完整候选、可信 CI 快照，或用户明确接受的精确 fingerprint 才能晋升为 `trusted_baseline`。baseline 绑定 commit、profile、bundle、structure、indexed paths、scope、tool/runtime、policy 和 evidence digest；后续身份变化会失效，旧版本保存在 history 中而不是被覆盖。delta 会明确报告 new、expanded、unchanged、reduced 和 resolved。

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
- 每次 flow 还会独立统计 `intra_capability`、`cross_capability` 和 `extended` 三条通道。`new`、`extract`、lifecycle 请求必须运行 extended；shared/canonical surface 仍会触发跨 capability 检查。
- 每条通道独立携带 scope digest、coverage、预算、完成状态、跳过原因和 evidence digest。任一 required channel 为 bounded/incomplete 时，全局重复结论只能是 `not_proven`。

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

changed-path 报告身份只使用路由真值、目标内容和实际参与扫描的 owner/candidate `source_fingerprint_digest`。无关 worktree 文件不会破坏 canonical report 去重，但任何参与判断的源文件变化都会使摘要失效。

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

### 有界授权 manifest

`authorization_request` 只是对当前 task/path/owner/route/pre-change snapshot/mutation envelope 的请求草案，不能创造权限。用户明确确认后，使用 `manage_authorization.py grant` 记录 grant；默认单次使用、24 小时过期，可显式授权最多 100 次且最长 30 天。每次状态变化进入摘要链 audit event，任何上下文、runtime/policy 或 mutation 变化都会失效；已 consumed、expired、invalidated 或 rejected 的 grant 不能因输入相同而恢复。

```powershell
python scripts/manage_authorization.py --repo <repo-root> request --route-report <full-flow-report.json>
python scripts/manage_authorization.py --repo <repo-root> grant --request-id <request-id> --authorization-source user --confirmation "<exact confirmation>"
python scripts/manage_authorization.py --repo <repo-root> consume --grant-id <grant-id> --route-report <current-full-flow-report.json>
python scripts/manage_authorization.py --repo <repo-root> inspect --grant-id <grant-id>
```

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
- [references/typed-findings-gate-todo.md](./references/typed-findings-gate-todo.md)

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
- `scripts/run_change_flow.py`
- `scripts/manage_authorization.py`
- `scripts/sync_feedback.py`
- `scripts/validate_router_bundle.py`

DeepSeek Harness 接入文件：

- `package.json`
- `integrations/deepseek-harness/index.js`
- `integrations/deepseek-harness/cordis.patch.yml`

## CI

GitHub Actions workflow 位于 [.github/workflows/ci.yml](./.github/workflows/ci.yml)，会执行：

- 安装依赖。
- 校验 skill 结构。
- 校验 DeepSeek Harness provider 语法和注册/加载 smoke。
- 用 `npm pack --dry-run` 校验 DSH 发布包不包含 `__pycache__`、`.pyc` 或其他本地运行时产物。
- 运行单元测试。
- bootstrap 自仓库 bundle。
- validate bundle。
- governance audit。
- freshness check。
- dependency direction、runtime cycle 与 public API check。
- central growth、800/1200 文件规模、forbidden root 与 exclusive owner structure check。
- route evaluation。
- capability-scoped reuse scan、隔离 worker 和严格完整性检查。
- typed finding schema、execution gate replay、可信 baseline、增量缓存、三通道 reuse、compact flow 与 authorization 状态机回归。
- 临时目录中的原子安装与 `--verify-only` 完整载荷校验。

## 边界与风险

需要明确：

- 首次 bootstrap 只是 first pass。
- 没有 profile 时，结果会偏保守。
- generated-only evaluation 只能说明系统自洽，不代表架构成熟。
- capability 命中正确不代表 action、secondary contract 或写入授权可靠；evaluation 未达阈值时仍为 `review_only`。
- 只有 `execution_gate.state` 决定当前写入状态；`action=review`、`review_required` 和 confidence 都不是独立门禁。
- `decision_confidence=high` 只说明 action/decision basis 稳定，不提供写权限。
- `action` 是建议动作，不是最终工程命令；execution gate、安全信封、typed findings、owner、canonical root 和生命周期约束优先级更高。
- `check_reuse` 的 `result_status=pass` 只有在 `completion_status=complete` 且 `evidence_complete=true` 时才表示目标 scope 已完成；bounded、timeout 和 incomplete 只能作为定向分析证据。
- 生命周期操作，例如 delete、merge、deprecate、replace、migrate，会产生强制 lifecycle evidence/gate；`review` 只是建议的调查方向。
- 这个 skill 给方向、证据和约束，最终实现方案仍应来自真实代码分析、测试和用户确认。

## 许可证

见 [LICENSE](./LICENSE)。
