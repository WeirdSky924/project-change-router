# Profile Examples

这些文件是最小可复制 profile 示例。

放置方式：

- 重命名为 `.project-change-router.yaml`
- 放到目标仓库根目录

可用字段：

- `profile_id`: profile 名称
- `capabilities`: capability 到路径的映射
- `ownership_rules`: 路径到 owner 的映射
- `module_overrides`: 对 layer / public_api / domain 的显式覆盖
- `contracts`: capability 的 scope / boundary / cross-capability / risk 约束
- `lifecycle`: capability 的版本、阶段、废弃和迁移信息
- `evaluation`: 人工确认过的路由回归用例
- `reuse_scan_scope`: dependency 邻居和未解析 changed-path 策略
- `reuse_scan_budget`: candidate、owner、全文比较和 fingerprint 阈值
- `reuse_scan_runtime`: soft/hard timeout、checkpoint、缓存和诊断策略
- `reuse_scan_retention`: canonical/checkpoint/diagnostic 与 fingerprint 保留上限

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
- 废弃或合并 capability 时，补 `superseded_by`、`deprecation_date`、`migration_note`

这些 reuse 运行时字段都是可选项。旧 schema-v1 bundle 缺少它们时，新 skill 使用代码默认值且不写回 bundle；不要为了获得默认 timeout 或 fingerprint 缓存而重建旧 bundle。

如果你想看“真实项目结构如何匿名抽象成 profile”，再看：

- `../calibration/README.md`
- `../calibration/anonymized-profile.yaml`

如果你想看“这个 skill 仓库自身如何把 scripts / references / examples / README 映射为治理能力”，看：

- `skill-repo.project-change-router.yaml`
