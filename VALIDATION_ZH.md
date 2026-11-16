# 验证记录

## 目录结构调整

已按 `v1.1-dexjoco-imagine` 重排：根级 `agent_skills`、`models`、`library`、
`references`，`src/wujiimagine` 按功能平铺；根级入口为 `run_imagine.py` 和
`run_imagine.ps1`。硬件示例配置在 `models/hardware`，任务配方在 `library/tasks`。

本次只复查结构调整影响的路径：已有 `checks/smoke.py` 通过，分层任务仍展开为
6 个节点/13 步，`run_imagine.py recipe skills` 列出 6 项内置机器人技能。
重建的 wheel 在隔离目录加载了 16 项流程 skill、20 个手关节及 6 项机器人技能，
确认包内没有旧 `_robotics` 子包。新安装包为
`output/wheel_structure/wuji_imagine-1.1.0-py3-none-any.whl`。
旧构建和迁移残留归档至 `tmp`，原始实验记录未改写。本次未连接真机。

## 初次实现的离线检查

2026-11-14，在本工作区使用 Python 3.11.5、NumPy 1.26.4、SciPy 1.17.1
完成以下相关离线检查。没有运行任务全集、连接机器人、修改本地标定或启动实物运动。

| 检查 | 结果 |
|---|---|
| `doctor` | 基础数值依赖与 MuJoCo 可用；RTDE/WujihandPy/RealSense 未安装；未连接硬件 |
| `demo` 轻量预演 | mock 短段抬升、匹配执行和 fresh RGB-D 比较完成；静止假设残差 0 m |
| `demo --engine mujoco` | 独立四粒子接触预演与比较完成；物体中心残差约 0.0476 m，如实保留 |
| 分层 compile | hierarchical_pick_lift 展开为 6 个节点、13 步 |
| 单次 mock 抓取配方 | pick_lift 完成；合成视觉抬升约 0.0598 m，相对 TCP 漂移约 0.000206 m |
| `checks/smoke.py` | 16 项 skill 可读；动作修改/重复预测/插入运动后比较被拒绝；局部残差和运行时快照可用 |
| localhost HTTP | 独立隐藏 mock 服务中 status/observe/execute/status 复用同一 session，序列 0→1，TCP 抬升 5 mm；结束后清理测试进程 |
| 独立 wheel | 无网络、无依赖安装构建成功；临时目录隔离加载得到 16 项流程 skill、20 个手关节及 6 个内置机器人技能 |

MuJoCo 代理与合成相机不是同一物理系统，约 4.8 cm 的残差不表示真机预测精度，
也没有作为通过/成功标志。上述所有 `physical_success` 保持 `null`。
mock 抬升来自合成夹持变量，仅验证数据与执行链路，不能据此声明实物抓取成功。

本次检查修复了迁移后的机器人技能资源命名空间残留，并核对快照包含独立运行时。
没有增加专家演示、世界验收证书、固定阶段数、仿真通过或多次真机重放前置条件。

可审阅的工作区产物：

- `output/smoke_kinematic/`：轻量闭环。
- `output/smoke_mujoco/`：物理预演及实测比较。
- `output/compiled_fixed/`：分层展开。
- `output/recipe_smoke/`：单次 mock 抓取记录。
- `output/wheel_final/wuji_imagine-1.1.0-py3-none-any.whl`：最终安装包。

仍未验证：实际 SDK/固件兼容性、工作站 TCP 与相机标定、真实关节映射、
完整机械臂/手壳扫掠碰撞、实物接触/滑移与任务完成。真机接入按
[HARDWARE_ZH.md](docs/HARDWARE_ZH.md) 使用现场配置进行。
