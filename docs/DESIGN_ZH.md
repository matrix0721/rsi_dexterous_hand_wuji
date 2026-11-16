# 从 DexJoCo skill 到 Wuji 真机

项目基于流程能力重新接线，未复制 DexJoCo 的 worker、动作维度或任务私有状态。
所有底层硬件代码已包含在 `src/wujiimagine`，来源是同工作区 `v1-wuji`。
包命名空间独立，安装时不会占用原 `wuji` 包。

目录组织遵循 `v1.1-dexjoco-imagine`：根级 `agent_skills`、`models`、`library`、
`references` 配合平铺的 `src/wujiimagine` 功能模块。设备适配在 `native.py`，
配方执行在 `execution.py`，机器人技能在 `robot_skills.py`；不嵌套原项目包结构。
根级入口为 `run_imagine.py` / `run_imagine.ps1`，原配方能力通过 `recipe` 子命令调用。

| 源项目能力 | 真机实现 | 证据与边界 |
|---|---|---|
| agent-runtime | LiveSession、Context、localhost RPC、核心提示 | 一个进程拥有设备；外部模型 host 自行接入 |
| learn-from-experts | 可选本地 references/index.json | 没有固定数量或仿真成功演示 |
| rgbd-perception | RealSense/录制 NPZ/工厂插件、反投影 | 固定眼在手外；插件负责其他安装方式 |
| world-modeling | ROI/聚类、法向、PCA、AABB、版本 | 可见表面；无自动分割/跨遮挡永久身份 |
| numerical-grasp-planning | 实际手 FK 接触引导搜索 | 近似骨架与凸包，不保证完整路径/摩擦闭合 |
| contact-planning | 抓取求解器 + 明确的短段目标 | 无通用工具角色编译器 |
| imagination | 运动学假设 / 可选 MuJoCo 粒子接触预演 | 独立数据与模型，绝不接设备 |
| robot-execution | UR RTDE / WujihandPy、动作前后记录 | 无 simulator reset，无自动命令重试 |
| tool-state-estimation | 同特征的 RGB-D 到手掌局部坐标比较 | 控制器工作流，无自动追踪器 |
| self-correction | 用户控制器的实测自由空间修正流程 | 不内置自主探测序列或修改标定 |
| learn-and-repair | 对齐比较、局部残差、JSON 局部修复 | 不声称完整动力学辨识或实物泛化 |
| controller-verification | 代码/运行时冻结、测量检查 | 无强制独立真机重放 |
| experience-and-evaluation | memory 事件、明确证据范围 | 真实布局与人工干预需记录 |
| data-collection | 稀疏 RGB-D / 动作 / 状态 / 失败前缀 | 无密集同步录制或 campaign coordinator |
| benchmark-generation | 真实工作站任务规格流程 | 不自动生成物理场景 |
| results-statistics | 按 report/events 的统计口径 | 不制造成功率、token 或零成本值 |
| blender | 未迁入 | 可使用抓取 HTML 预览；无 Blender 时间线功能 |

预演绑定动作摘要、起始关节/TCP、序列号与世界版本。提供 prediction id 才执行对应性
检查；普通实测执行无需预演。动作开始即推进序列，即使动作部分失败也不能重用旧预测。
相机后处理失败保留完成前缀，不触发运动重试。比较必须发生在对应执行后且没有后续运动。

MuJoCo 的物体代理来自可见 AABB，未见背面/凹槽/机器人外壳仍未知；质量、摩擦和
参数离散只是显式假设。预测中没有官方任务成功函数。模型与合成 mock 不共享物理引擎，
因此其残差可能很大，这是有意义的诊断，不是测试失败或真实动力学精度验证。

机器人 JSON 分层技能、项目流程 SKILL.md 和 Codex 安装 skill 分别管理。本次没有
写入全局 Codex 技能目录或改变既有项目。源模型的许可证随包保留。
