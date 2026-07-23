# Profile Examples

这些文件是最小可复制 profile 示例。

放置方式：

- 重命名为 `.project-change-router.yaml`
- 放到目标仓库根目录

可用字段：

- `profile_id`: profile 名称
- `capabilities`: capability 到路径的映射
- `ownership_rules`: 路径到 owner 的映射
- `capability_ownership`: stable capability 到真实 primary owner、不同 reviewers 和 escalation group 的映射
- `module_overrides`: 对 layer / public_api / domain 的显式覆盖
- `contracts`: capability 的 scope / boundary / cross-capability / risk 约束
- `lifecycle`: capability 的版本、阶段、废弃和迁移信息
- `evaluation`: 人工确认过的路由回归用例
- `guardrails.architecture_baseline`: 只登记精确匹配的依赖、runtime/type-only cycle 或 public API 旧债
- `guardrails.central_growth_baseline`: 冻结中央文件/符号的 commit、规模和成员净增长
- `guardrails.forbidden_implementation_roots`: 禁止新增正式实现的 legacy、compat 或非 canonical 根
- `guardrails.exclusive_source_owners`: 限定某类实现只能存在于一个 canonical owner
- `reuse_scan_scope`: dependency 邻居和未解析 changed-path 策略
- `reuse_scan_budget`: candidate、owner、全文比较和 fingerprint 阈值
- `reuse_scan_runtime`: soft/hard timeout、checkpoint、缓存和诊断策略
- `reuse_scan_retention`: canonical/checkpoint/diagnostic 与 fingerprint 保留上限
- `risk.review_phrases`: 仅属于当前仓库、必须强制 review 的精确请求短语

示例文件：

- `early-repo.project-change-router.yaml`
- `python-monorepo.project-change-router.yaml`
- `ts-workspace.project-change-router.yaml`
- `mixed-repo.project-change-router.yaml`
- `skill-repo.project-change-router.yaml`
- `reuse-runtime.project-change-router.yaml`

早期仓库建议：

- 先只写 `ownership_rules`
- 尽量不要一开始就写完整 `capabilities`
- 把 owner 写成 `provisional:<name>`，避免误导成正式治理结构
- 一旦 capability 被多次真实命中，再补 `contracts`、`public_entries` 和 curated evaluation cases
- 只有真实案例达到 30 个、覆盖六类 `calibration_category`、并声明 catalog-valid `expected_primary_capability` 后才开启 evaluation enforcement；生成案例和 legacy membership 列表不能授权 `normal`
- 废弃或合并 capability 时，补 `superseded_by`、`deprecation_date`、`migration_note`
- stable capability 必须通过 `capability_ownership` 显式声明稳定 primary owner 和不同 reviewer；缺失记录、自动占位 owner、`UNKNOWN`、unassigned 或 `provisional:*` 不能授权无人值守写入

```yaml
capability_ownership:
  - target: order-capability
    primary: order-maintainers
    reviewers:
      - order-architecture-reviewers
    escalation_group: architecture-council
```

架构基线建议先保留显式空集合，再按真实证据逐项登记：

```yaml
guardrails:
  architecture_baseline: []
  central_growth_baseline: []
  forbidden_implementation_roots: []
  exclusive_source_owners: []
```

`architecture_baseline` 不是 glob 豁免。每项必须包含精确 rule identity、稳定 owner、退出阶段和由当前 finding 计算出的 SHA-256 fingerprint。`central_growth_baseline` 必须绑定真实 comparison commit、path、symbol、owner 和退出阶段。已有债务可以被精确登记以先阻止新增，后续应持续降低基线。

下面只展示字段形状；复制时必须把路径、commit、limit、owner、退出阶段和 fingerprint 全部替换为目标仓库的实测值：

```yaml
guardrails:
  architecture_baseline:
    - id: dependency-debt-001
      rule: dependency-direction
      source: src/orders/service.py
      target: src/http/order_routes.py
      owner: order-capability
      exit_stage: architecture-stage-2
      fingerprint: "<lowercase-64-character-sha256>"
  central_growth_baseline:
    - id: application-composition-root
      kind: python-class-remove-only
      path: src/application.py
      symbol: Application
      source_commit: "<full-comparison-commit>"
      owner: application-composition
      exit_stage: architecture-stage-3
      max_file_lines: 780
      max_methods: 24
      max_public_methods: 12
    - id: api-composition-function
      kind: python-function-remove-only
      path: src/http/app.py
      symbol: create_app
      source_commit: "<full-comparison-ancestor-commit>"
      owner: http-composition
      exit_stage: architecture-stage-3
      max_file_lines: 620
      max_symbol_lines: 410
      max_nested_functions: 18
      max_decorated_handlers: 16
      tracked_members: [legacy_health_handler]
      max_tracked_members_present: 1
  forbidden_implementation_roots:
    - id: no-new-order-runtime-under-legacy
      path: legacy/order_runtime
      owner: order-capability
      exit_stage: permanent
  exclusive_source_owners:
    - id: order-sql-owner
      root: src
      path_pattern: "src/**/*.py"
      owner: order-persistence
      allowed_paths:
        - src/orders/persistence/postgres_adapter.py
      forbidden_source_patterns:
        - "\\b(?:select\\b.*?\\bfrom|insert\\s+into|update|delete\\s+from)\\s+orders\\b"
```

Python `TYPE_CHECKING` 与 TypeScript `import type`/type-only export 会被记录为 type-only edge，不应登记成 runtime-cycle 旧债。parser/resolver diagnostic 需要修复证据完整性，不能通过 baseline 消除。

这些 reuse 与 0.3 架构治理字段都是可选项。旧 schema-v1 bundle 缺少它们时，新 skill 使用代码默认值且不写回 bundle；不要为了获得默认 timeout、fingerprint 缓存或空架构集合而重建旧 bundle。Skill 安装和 `--verify-only` 也不会搜索或修改任何项目 bundle。0.3 保持 reuse engine API v2，并新增 architecture governance API v1。

如果你想看“真实项目结构如何匿名抽象成 profile”，再看：

- `../calibration/README.md`
- `../calibration/anonymized-profile.yaml`

如果你想看“这个 skill 仓库自身如何把 scripts / references / examples / README 映射为治理能力”，看：

- `skill-repo.project-change-router.yaml`
