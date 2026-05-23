# Anonymized Calibration Case

这组样例来自一个真实的 Python + React 多模块仓库的结构特征抽象，不包含原始业务文本、项目名或团队标识。

保留的是真实架构形态：

- Python 后端
- React/TypeScript 前端
- API 路由层
- service orchestration 层
- assistant/context 子系统
- workflow adapter 子系统
- migrations
- tests

目标：

- 作为真实校准参考，而不是纯 fixture
- 帮助使用者理解 profile 怎么从真实仓库结构里抽出来
- 帮助作者继续补误判回归测试

包含文件：

- `anonymized-structure.md`
- `anonymized-profile.yaml`
- `anonymized-module-map.yaml`
- `anonymized-route-cases.yaml`
- `anonymized-feedback.json`

使用方式：

1. 先读 `anonymized-structure.md`
2. 看 `anonymized-profile.yaml` 如何表达真实结构约束
3. 看 `anonymized-route-cases.yaml` 如何把真实场景转成校准用例
4. 把这些模式映射到你自己的仓库，而不是直接照抄名字
