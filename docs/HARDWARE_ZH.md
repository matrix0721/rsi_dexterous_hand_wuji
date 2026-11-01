# 真机接入与标定

本版面向一台 UR5e 和一只 **Wuji Hand 1 右手**。内置驱动采用 `ur_rtde`、
`wujihandpy`，视觉采用固定安装的 RealSense RGB-D。当前工作区没有连接设备，
以下步骤是待在实际工作站执行的接入说明，不是已完成的实物验证记录。

## 1. 坐标与装配

所有长度用米、角度用弧度。`T_A_B` 把 B 系中的点变换到 A 系：
`p_A = R_A_B @ p_B + t_A_B`。相机光学系为 x 向右、y 向下、z 向前。
机械臂目标 `pose=[x,y,z,rx,ry,rz]` 中后三项为旋转向量，不是欧拉角。

规划手掌系是 `wuji_hand1_right.json` 的 `right_palm_link`。
`hardware.tcp_flange_pose` 必须表示 **UR 法兰 → 该手掌根部** 的刚体变换。
驱动调用 `setTcp` 后，RTDE 的 TCP 位姿直接对应规划手掌根部，不能再叠加一次
法兰偏移。安装转接板、左右手、软垫厚度改变时，应重新核对它。

UR 上设置合适的负载和重心；配置 `payload_kg`、`payload_cog_m` 会通过 SDK 写入。
重心在法兰/工具安装所用的 UR 工具参考系表达，依照控制器说明测量，不要填入
世界坐标中的物体位置。示例文件中的数值仅为占位，负载包含安装板和手。

手指顺序采用官方 URDF / SDK 的 F1…F5，每指 J1…J4；F1 为拇指。
开源文件保存的是 20 个一维弧度值，写 SDK 时 reshape 为 `(5,4)`。
不使用仿真器中的 actuator 排序，也不把其他型号的姿态直接复制到本手。

## 2. 工作站配置

```bash
python -m pip install -e ".[robot,camera]"
```

复制 `configs/robot.example.json` 为 `configs/robot.local.json`，填写 UR 地址、
Wuji 序列号、相机序列号、安装 TCP、负载、相机外参、桌面高度、ROI 和工作空间。
本地配置已被 Git 忽略。无需把地址或序列号写进源码。

UR 通过以太网、手通过 USB 连接。按 [ur_rtde 官方文档](https://sdurobotics.gitlab.io/ur_rtde/)
准备控制器远程控制模式与网络权限；本版使用默认控制脚本上传方式。
不要同时运行另一个会占用机器人控制的进程。
Wuji 的驱动权限、固件和 SDK 版本按 [官方 SDK 说明](https://github.com/wuji-technology/wujihandpy)
配置。官方新版统一 SDK 与 `wujihandpy` 的接口不同，本项目没有把两者混用。

先读状态：

```bash
python run_wuji.py probe --backend real --config configs/robot.local.json
```

该命令只创建 RTDE receive 通道和手的读取对象。检查手的实际姿态、`handedness`
与关节错误码。默认模型要求右手，驱动按官方枚举值 `Right=0` 检查。
若实际硬件是其他代际，应提供对应模型并修改 SDK 适配器，再开始运行。

## 3. 相机标定

内置相机是**眼在手外**，`camera.T_base_camera` 为固定的相机光学系到 UR 基座系
变换。示例外参不是你的实测外参，不能仅将 `calibrated` 改为 true 后运行。

可使用已有标定工具，也可采集对应点：至少三个不共线的点，建议取分散且有一定
高度差的 6–10 个点。将相机反投影得到的点和同一物理点在基座系中的坐标分别写入
`camera_points_m`、`base_points_m`。TCP 不等于标定探针尖端时先补偿探针偏移。

```bash
python tools/fit_camera.py examples/camera_points.json --output outputs/camera_fit.json
```

此处示例是人工构造点。真实使用时替换输入，将输出的 `T_base_camera` 写进
本地配置。查看 RMS、最大残差，并用未参与拟合的物理点核查；拟合残差小不等于
深度尺度、TCP 和全工作区误差都正确。没有硬编码残差阈值，按目标尺寸判断。

`camera.table_z_m` 必须是桌面在 UR 基座系中的实际高度。
默认算法按水平桌面裁剪；斜桌面、墙面或其他背景可通过相机/感知插件处理。
`roi_pixels=[x0,y0,x1,y1]` 为彩色对齐图像中的像素范围；null 表示不做 ROI 裁剪。
让目标尽量占据 ROI，避免把机器人本身当成最大的物体簇。内置基线没有完整机器人
外壳自遮挡模型。

RealSense 将深度对齐至 RGB，读取实际深度比例；若彩色相机有畸变，预计算 SDK
反投影射线，不把畸变图像直接当针孔图。录制 NPZ 同时保存这些射线。
每次 capture 排空旧队列后等待下一帧；时间戳使用主机接收时间，没有声称多设备
硬件同步。手眼安装或多相机同步需要自定义工厂插件。

## 4. 候选检查和首个实验

```bash
python run_wuji.py capture --backend real --config configs/robot.local.json --output captures/target
python run_wuji.py plan --config configs/robot.local.json --frames captures/target/frame.npz --output outputs/target_plan
```

查看 `grasp_preview.html`，核对点云高度、目标位置、手的朝向及关节是否符合实物。
指腹偏移在手模型 JSON 的 `pads` 中，骨架与手掌近似在 `hand.py` 中。
若存在凹形物体、工具使用部位预留或其他接触需求，可修改代价或加入候选生成器；
不需要改动执行器协议。所有候选不可用时，先改变 ROI/相机视角或几何参数，
不要把低接触距离误当成能抓住。

在示教器中将空手置于目标上方、进近路线清楚的开始位姿。当前实现不负责从任意
起始关节状态绕过桌边、设备或线缆，也没有完整 UR5e 连杆/手壳路径碰撞模型。
UR 的目标安全限制和 IK 只检查控制器对应的目标条件，不能替代整个外部场景的
轨迹碰撞规划。骨架筛选只检查候选状态，预张开、进近和闭合扫掠须在工作站核对。

完成这些工作后，将本地配置 `hardware.calibrated` 改为 true：

```bash
python run_wuji.py run --backend real --config configs/robot.local.json --task examples/pick_lift.json
```

默认速度 0.04 m/s、加速度 0.10 m/s²、短抬升 0.06 m，可按工作站修改。
这些是首次调试的示例参数，不是设备性能上限或安全认证值。只保留一层明确的
真机选择与一份标定配置，没有每动作重复确认流程。

## 5. 反馈、中断与结果

机械臂采用异步 `moveL`，主机循环监测设备错误、保护状态、TCP 力和超时。
手使用 SDK realtime controller，以关节速度限制插值；负载达到设定比例的关节
停止继续收紧，其他关节可继续接触。负载读数依 SDK 为电流等效值，**不是牛顿制
指尖力传感器**；没有将电流比例标为真实指尖压力。
TCP 力阈值使用控制器报告的力模长，需要正确设置负载并核对无接触时的偏置。

异常或 Ctrl+C 会触发机械臂 stopL，并尽力将手目标设为当前测量姿态；不会主动
张手或自动倒放轨迹。停止依赖主机通信和设备固件，现场保留可用的急停。
执行结束不会自动回家或松开物体。持物实验应有接收托盘，结束后按工作站流程
放下物体；不要依赖进程关闭维持无限时间的夹持。

默认一次实验，无自动真机修复重试。失败报告提供最后动作、图像和异常。
修改技能/视角后再启动下一次运行即可。抬升观察只能验证相机看到的短时运动；
要评价实物抓取稳定性、保持时间和完整任务，请另行记录人工观察或实际传感证据。

1.1 版可显式设置 `--repair-attempts`，在同一个活会话中从失败的子技能动作继续。
内置真机修复仅在抓取运动前重规划，或对过期/丢失/抬升不明的视觉结果重新拍摄；
不会按合成示例继续抬升来猜测是否抓住，也不会在设备停止后重播动作。
`repair`、`verify`、`develop` 命令都是离线处理，不恢复历史现场或连接设备。
子技能的 `verified_real` 仅表示其声明的检查在真实运行中通过，不能替代实物任务评价。
详见 [分层技能和修复流程](SKILLS_REPAIR_ZH.md)。
