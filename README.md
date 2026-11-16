# Wuji Imagine v1.1

面向 **UR5e + Wuji Hand 1 右手 + RGB-D** 的独立真机项目，按
`v1.1-dexjoco-imagine/agent_skills` 的观测、世界建模、预演、执行、比较和修复流程实现。
真机驱动与手模型复用自 `v1-wuji`，源码已包含在本项目，运行时不依赖兄弟项目。

文件结构按 `v1.1-dexjoco-imagine` 组织，底层驱动来源不决定项目布局：

```text
v1.1-wuji-imagine/
  agent_skills/           # 根级流程 skill 注册表与正文
  checks/                # 必要离线检查
  docs/                  # 设计、硬件、修复说明
  examples/              # Python 控制器示例
  library/               # 机器人技能、任务配方与后续积累
  models/                # 手模型、许可证、hardware 配置
  references/            # 可选工作站演示索引
  src/wujiimagine/        # 按功能平铺的会话、执行、规划与驱动模块
  tools/                 # 标定和辅助脚本
  output/                # 会话与实验产物
  tmp/                   # 临时文件与旧构建归档
  run_imagine.py
  run_imagine.ps1
  pyproject.toml
```

`native.py` 管真机驱动，`execution.py` 管配方执行，`grasp_planning.py` 管抓取搜索；
`skills.py` 管流程 skill，`robot_skills.py` 管机器人 JSON 技能。源码没有 `_robotics`
子项目或独立的根级机器人入口。`run_imagine.py recipe ...` 接入完整配方命令。
安装包构建时收集根级资源，源码中不维护重复资源副本。

提供持久会话、Python 控制器、localhost HTTP 工具、16 项流程 skill、真实手部 FK
抓取搜索、独立 MuJoCo 预演、分层 JSON 任务、局部修复和子技能积累。
**当前验证为离线合成输入，尚未连接硬件或完成实物实验。**

## 快速开始

在本目录执行，Python 3.10+：

```powershell
python -m pip install -e .
python run_imagine.py doctor
python run_imagine.py skills
python run_imagine.py demo --output output/demo
python run_imagine.py run --controller examples/controller.py --output output/controller
```

默认 `mock`，无需机器人 SDK、密钥、模型权重或仿真器。可选物理预演：

```powershell
python -m pip install -e ".[physics]"
python run_imagine.py demo --engine mujoco --output output/physics
```

`kinematic` 明确预测 stationary / attached / translation 刚体运动假设；
`mujoco` 使用可见物体包围盒、桌面和五个运动学指尖球做独立接触预演，支持质量、
摩擦参数粒子。两者均不控制设备，不提供任务成功判定，也没有完整机械臂路径碰撞保证。

## 持久会话与 agent 接入

```powershell
python run_imagine.py serve --output output/session01
```

进程输出 `session.json` 路径，服务保持机器人/相机状态；另一个终端：

```powershell
python run_imagine.py call --session output/session01/session.json --tool status
python run_imagine.py call --session output/session01/session.json --tool observe
python run_imagine.py run --session output/session01/session.json --controller examples/controller.py
```

`--params-file args.json` 传递工具参数；也可使用 `--params` JSON。
服务生成 `agent_prompt.md`，包含会话说明和三项核心流程 skill。
外部 Codex/Claude/其他模型 host 可读取提示，通过 Python 或命令行调用同一会话。
项目不内置付费模型调用，也不依赖某个模型 CLI。HTTP 绑定 127.0.0.1，descriptor
包含访问 token；所有工具串行进入同一设备所有者，不自动重试 HTTP 请求。

```python
from wujiimagine import Context

ctx = Context("output/session01/session.json")
print(ctx.skill("imagination")["text"])
world = ctx.world()   # 当前 RGB-D；多物体时使用 roi 或 target_hint
actions = [{"op": "lift", "height_m": 0.005}]
p = ctx.imagine(actions, hypothesis={"relation": "stationary"})
execution = ctx.execute(actions, prediction=p["id"])
if execution["status"] == "completed":
    feedback = ctx.compare(p["id"])
    ctx.remember("物体未随空手抬升", evidence=[p["id"], feedback["after_observation"]])
```

`world()` 为深度聚类、法向和 PCA，可见中心不是完整物体质心；默认最大簇，
指定 hint 后为最近簇。它没有自动语义检测和永久身份锁，遮挡后要检查身份。
`observe()` 只记录 RGB-D 与本体感知；`world_state()` 读取历史缓存。
`pixel_to_world([u,v])` 从最新帧反投影，支持相机畸变射线。

预演可选，普通执行无需先建模、读取专家或通过仿真。提供 prediction id 时，
系统只接受相同起始状态和动作序列，并防止重复消费；比较拒绝不完整执行和中间插入运动。
执行后的相机错误单独记录，不将已执行动作变成“未执行”。

## 真机接入

```powershell
python -m pip install -e ".[robot,camera]"
Copy-Item models/hardware/robot.example.json models/hardware/robot.local.json
```

填写实际地址、序列号、负载、法兰到手掌 TCP、相机外参、桌面、ROI、工作区和速度。
按 [硬件与标定说明](docs/HARDWARE_ZH.md) 核对实测标定，再设置
`hardware.calibrated=true`。默认模型为 Hand 1 右手；其他型号/左手需改模型和驱动。

```powershell
# 仅读设备；不创建运动控制器
python run_imagine.py probe --backend real --config models/hardware/robot.local.json
# 只连接相机；不会创建机械臂运动控制器
python run_imagine.py capture --backend real --config models/hardware/robot.local.json --output captures/target
# 用录制帧离线规划
python run_imagine.py plan --config models/hardware/robot.local.json --frames captures/target/frame.npz --output output/plan
# 以下才创建真机控制会话，之后通过同一 session 的 Context/控制器执行动作
python run_imagine.py serve --backend real --config models/hardware/robot.local.json --output output/real01
```

`run --backend real --controller ...` 也可直接拥有设备；已有服务时用 `--session`。
不要同时开启两套设备所有者。真机不使用历史帧驱动，不提供 simulator reset。
创建 real 会话会连接 RTDE、设置 TCP/负载；手部在首次手命令时使能。

动作 `move_tcp.pose=[x,y,z,rx,ry,rz]` 是 UR 基座中的米与旋转向量弧度；
`set_hand.q` 是 F1…F5/J1…J4 顺序的 20 个弧度值。
`lift.height_m` 沿基座 Z；`wait.seconds` 保持监测。
保留驱动层的设备状态、IK、工作区、关节范围、负载/力和超时检查，参数在配置中可调。
不增加每动作确认、强制专家/预演、固定阶段数或多轮验证要求。
设备/执行异常停止当前会话，保存已执行前缀；不自动张手、回家或重放。

## 抓取、分层技能与修复

`ctx.plan_grasp()` 返回可见表面的接触引导候选和交互 HTML，联合搜索手掌 6D 和
20 个真实 Wuji 关节。`usable` 只是当前几何筛选，不能证明摩擦力闭合或抓取成功。
普通控制器可用候选的 `pregrasp_pose`、`tcp_pose`、`q` 生成明确动作。

保留原执行器的完整分层接口，使用本项目的资源命名空间：

```powershell
python run_imagine.py compile --task library/tasks/hierarchical_pick_lift.json --output output/compiled
python run_imagine.py run --task library/tasks/pick_lift.json --output output/pick
# 需要原接口的额外参数时直接使用 run_imagine.py recipe
python run_imagine.py recipe demo --task library/tasks/repair_short_lift.json --repair-attempts 1 --develop-subskills --output output/repair
python run_imagine.py recipe verify --report output/repair/report.json
```

分层任务是 `task → skill → subskill → primitive`，小任务也可平面 JSON。
基础动作包括 observe、plan_grasp、open_hand、move_pregrasp、move_grasp、close_grasp、
grasp、lift、verify_lift、move_tcp、set_hand、place、wait。
`run_imagine.py recipe --help` 提供 compile/develop/repair 和相机插件等参数。
默认修复只生成建议；只有显式指定次数才做该次实验支持的局部恢复，真机设备故障不重播。

`ctx.compare(id)` 保存对齐后的物体与 TCP 残差。检查目标身份后，
`ctx.learn_dynamics(id, identity_confirmed=True)` 保存当前会话的局部平移残差，
同一动作/引擎/假设可以 `imagine(..., apply_residual=True)` 使用。它不是质量/摩擦辨识，
也不证明独立泛化；用新观测检查修正。

`ctx.operation(...)` 是可选阶段记录；`ctx.check(condition)` 使用实际测量的节点条件。
阶段注释不自动等于通过测量。
`ctx.freeze(controller, dependencies=[...])` 快照控制器、声明的依赖、运行时、skill 和哈希。
快照可通过 `run_frozen.py run --controller controller.py ...` 显式复用，不自动做真机排练。

## 流程 skill 与项目范围

注册表位于 [agent_skills/index.json](agent_skills/index.json)，
完整的源项目对应关系见 [迁移说明](docs/DESIGN_ZH.md)。本版提供 16 项按需流程说明。
`agent-runtime`、`robot-execution`、`controller-verification` 写入服务的核心提示；
其余通过 `ctx.skill(name)` 读取。读取 skill 不执行动作、不要求通过摘要证书。

Blender 表面融合、自动开放词汇分割、通用工具机构推断、任务场景自动生成、密集同步录制、
付费模型运行器未迁入。数据采集、评测和统计 skill 描述当前记录可支持的工作流，
没有将这些流程说明冒充完整的自动化系统。

## 记录与必要验证

```text
output/<session>/
  session.json, agent_prompt.md       # serve 才生成，descriptor 不公开
  session_config.json, report.json, events.jsonl
  observations/o*.npz, o*.json       # RGB / depth / K / 外参 / 时间 / robot
  worlds/w*.npz, w*.json
  plans/g*.json, g*.html
  predictions/p*.json, executions/e*.json, comparisons/p*.json
  robot/trace.jsonl                  # 原执行器细节与手反馈
  controllers/<hash>/                # 显式冻结时生成
```

图像采样发生在 observe/动作块结束，不是高频伺服视频。
命令完成、视觉抬升、测量条件通过与完整物理任务成功分开记录；
`physical_success` 默认 `null`，合成结果不继承旧项目的真机成功声明。

只做相关离线检查：

```powershell
python checks/smoke.py
```

验证记录见 [VALIDATION_ZH.md](VALIDATION_ZH.md)。无需跑任务全集或反复物理重放。
许可及来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
