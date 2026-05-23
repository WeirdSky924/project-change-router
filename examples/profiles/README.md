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

示例文件：

- `python-monorepo.project-change-router.yaml`
- `ts-workspace.project-change-router.yaml`
- `mixed-repo.project-change-router.yaml`
