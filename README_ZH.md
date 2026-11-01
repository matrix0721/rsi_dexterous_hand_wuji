# v1-wuji：UR5e + Wuji 手图像驱动真机实验

目录名、项目、包发布名和报告统一使用 `v1-wuji`。
这是可以独立安装、的实验项目，继承三个仿真项目的流程设计，
采用独立的小型实现，无需复制父项目、仿真器、旧轨迹或模型权重。

当前提供离线演示、RGB-D 录制/回放、目标表面估计、手部姿态搜索、真机适配器、
分层 JSON 技能、局部 repair-verification、子技能积累、视觉抬升观察和实验记录。
**尚未进行真机连接或实物抓取验证。**
内置模型对应 **Wuji Hand 1 右手、5×4 关节**。Hand 2、左手和其他机械安装方式
需要替换运动学参数及 SDK 映射，不应沿用现有角度。

## 快速运行

在 Windows PowerShell 或 Linux 终端进入本目录：

```bash
python -m pip install -e .
python run_wuji.py demo --output outputs/demo
python run_wuji.py plan --output outputs/plan
```

打开 `outputs/plan/grasp_preview.html` 可拖动旋转、缩放并切换候选。
默认输入是标记为 `synthetic_fixture` 的合成 RGB-D，默认机器人为 `mock`。
演示运行约数秒至数十秒，耗时随候选数量、优化迭代和电脑性能变化。
已安装 NumPy、SciPy 时，可以直接用 `run_wuji.py`，无需安装硬件 SDK。

## 流程

```text
RGB-D 相机 / NPZ 回放
  → 标定反投影、桌面过滤、ROI、体素聚类
  → 可见表面、局部法向、PCA 位姿及歧义提示
  → 接触引导姿态搜索：手腕 6 维 + 手部 20 关节
  → 手部预张开、预抓取、接近、按反馈闭合
  → 小幅抬升、重新拍摄、检查目标与 TCP 的相对变化
  → 记录、诊断建议、人工修改技能后继续实验
```

感知默认选 ROI 内最大的物体簇；抬升后选择离预期目标位置最近的簇。
适合先从独立、刚性、深度可测的小物体开始。多个相邻物体、透明/反光表面、
强遮挡和对称物体会影响估计。PCA 的平移是**可见表面中心**，不是完整物体质心；
姿态可能有轴交换或符号歧义，算法不把它当作精确 CAD 配准结果。

## 手部位姿算法

代码与配置统一使用 `contact_guided_pose_search` / “接触引导姿态搜索”。
它将几何预处理和候选搜索分开：一次建立 KD-tree 和近似凸包，多方向播种，
再用最小二乘联合优化手腕与关节。目标包括指腹接近表面、法向相对、拇指与其他
接触点形成对向分布、骨架穿透代价、异指间距、桌面与可见邻近物体的间距。

默认主动接触为拇指、食指、中指。内置指腹位置和骨架半径是近似值，
真机需按软垫/外壳修改。候选 `usable` 仅表示通过当前几何筛选；凸包会填补凹槽，
点云看不到背面，骨架不能覆盖整个外壳，也不证明摩擦力闭合或完整机械臂路径无碰撞。
法向对向程度默认作为排序代价，不作为单视角的硬通过门槛；需要时可设置
`planning.max_opposition_dot`。感知中的 `position_sigma_m` 是几何启发式量，
尚未通过真机标定为统计协方差。

## 真机入口

完整步骤见 [真机接入与标定](docs/HARDWARE_ZH.md)。仅需一份本地工作站配置，
不设置反复确认、成功证书、仿真通过或多轮重放前置条件。

```bash
python -m pip install -e ".[robot,camera]"
# 将 configs/robot.example.json 复制为 configs/robot.local.json，填写实际值并完成标定。
python run_wuji.py probe --backend real --config configs/robot.local.json
python run_wuji.py capture --backend real --config configs/robot.local.json --output captures/target
python run_wuji.py plan --config configs/robot.local.json --frames captures/target/frame.npz --output outputs/real_plan
python run_wuji.py run --backend real --config configs/robot.local.json --task examples/pick_lift.json
```

`probe` 仅读取 UR 状态和手部反馈，不创建 RTDE 控制器，不使能手。
`capture` 只连接相机；`plan` 只生成候选；`run --backend real` 才实际执行。
默认 `hardware.calibrated=false`，标定后在本地配置改为 `true`。
真实执行使用活相机，不允许通过 `--frames` 用历史图像驱动机器人。

运行中必要检查集中在驱动边界：有限数值、关节范围、TCP 工作区、控制器目标限制与
IK、通信/设备错误、运动超时、TCP 力阈值和逐关节负载停止。所有实验参数集中可调，
不对每个小动作附加独立验证流程。中断时停止机械臂并尽力维持手部当前姿态，
不自动张手。进程/USB/电源丢失时的保持行为由设备和固件决定，软件不能保证持物。

## 技能与扩展

1.1 版默认按 `task → skill → subskill → primitive` 展开任务。内置抓取任务包含
`pick.acquire`、`pick.raise`，并进一步拆成规划、接近、闭合子技能。每个节点保留
参数、检查结果和失败位置；成功叶节点可以在父任务失败时独立发展和复用。

```bash
python run_wuji.py compile --task examples/hierarchical_pick_lift.json --output outputs/compiled
python run_wuji.py demo --task examples/repair_short_lift.json --repair-attempts 1 --develop-subskills --output outputs/repair_demo
python run_wuji.py verify --report outputs/repair_demo/report.json
```

默认只执行一次并生成修复建议。显式设置 `--repair-attempts` 后，按失败动作局部
继续，用原目标判据验证；真机不照搬仿真的 reset 或完整重播。详见
[分层技能、修复与子技能发展](docs/SKILLS_REPAIR_ZH.md)。

`examples/pick_lift.json` 是最小抓取实验，`examples/pick_place.json` 展示分段运输和
放置。放置坐标是示例值，需改成真实坐标。支持的动作：

| 动作 | 输入 / 行为 |
|---|---|
| `observe` | 重新拍摄并估计目标 |
| `grasp` | 重拍、搜索、预张开、预抓取、接近、反馈闭合；可选 `candidate` 索引 |
| `plan_grasp` / `open_hand` / `move_pregrasp` / `move_grasp` / `close_grasp` | 将抓取拆成可定位和组合的更小动作 |
| `lift` | 沿基座 Z 抬升，可选 `height_m` |
| `verify_lift` | 对照抓取前观测，检查抬升和相对 TCP 漂移 |
| `move_tcp` | `pose: [x,y,z,rx,ry,rz]`，旋转向量制 |
| `set_hand` | `q` 为按 F1…F5、J1…J4 排列的 20 个弧度值 |
| `place` | 到给定 `pose` 后张手，后续退回由下一条动作指定 |
| `wait` | `seconds`，真机期间持续监测 |

JSON 技能可以由模型生成，也可手写；本版不内置在线模型服务调用，避免强制密钥和
外部服务依赖。Python 实验可直接组合 `Session` 与驱动接口，不限制为 AST DSL。

自定义相机：`--camera-factory my_camera:create`，函数 `create(config)` 返回实现
`capture() -> Frame`、`close()` 的对象。插件是受信任的本地 Python 代码。
可接入其他 RGB-D 相机、多视角融合或外部分割器；内置实时实现使用 RealSense，
视角为固定的眼在手外相机。相机装在手腕上时需要插件按每帧 TCP/FK 更新外参。

```bash
# 离线感知和姿态回放，不接机器人
python run_wuji.py plan --frames captures/target/frame.npz
# 导出实验收据；保留 mock / real、失败及未验证信息，不自动标成成功技能
python run_wuji.py export --report outputs/demo/report.json
```

`export` 保留实验收据；`develop` 或 `--develop-subskills` 另将已完成节点提取为
`library/skills/` 中可调用的参数化技能。它们带有原节点版本和 mock/real 证据范围，
不自动晋级为实物成功。`--repair-provider module:function` 可接入模型修复和新分解，
没有强制模型服务或固定编程沙箱。新场景仍重新观察和规划。

## 输出、验证与开源

```text
outputs/<run>/
  source_recipe.json、skill_tree.md、report.json
  development.json（启用子技能发展时）
  attempt_01/
    recipe.json、hierarchy.json、config.json
    perception/001.npz、001.json …
    grasp_plan.json、grasp_preview.html
    trace.jsonl、report.json、diagnosis.json、repair_proposal.json（失败时）
  attempt_02/ …（启用修复且需要时）
    repair_verification.json
```

`visual_lift_observed` 表示相机观测到目标运动符合短抬升条件，不代表其他任务成功。
目标身份采用空间关联，遮挡和错误关联仍可能误判。无真值或人工实测时
`physical_success` 保持 `null`。没有借用父项目的成功记录。

```bash
python -m unittest discover -s tests -v
```

测试只覆盖离线集成、标定和几个关键失败路径，CI 不安装真机 SDK、不连接网络设备、
不执行仿真任务集合。验证范围见 [VALIDATION_ZH.md](VALIDATION_ZH.md)。

新代码使用 MIT，手模型保留原 MIT 许可；研究出处见
[第三方说明](THIRD_PARTY_NOTICES.md)。直接将本目录作为 GitHub 仓库根目录即可，
CI 的工作目录已按独立仓库设置。`.gitignore` 排除设备配置、录制数据、实验输出和
本地环境。标准源码包含手运动学小文件，不依赖上级目录。架构取舍与参考项目的
对应关系见 [设计说明](docs/DESIGN_ZH.md)。
