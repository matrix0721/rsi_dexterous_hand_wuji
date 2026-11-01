# 分层技能、局部修复与子技能发展

1.1 版加入任务到动作的逐层展开、失败定位、repair-verification 和符号子技能积累。
旧的平面 JSON 动作仍可执行。新默认任务使用如下结构：

```text
task.pick_lift                       task：抓取并观察抬升
├─ pick.acquire                     skill：获取目标
│  ├─ grasp.prepare                 subskill：拍摄与规划
│  │  └─ plan_grasp                 primitive
│  ├─ grasp.approach                subskill：张手和接近
│  │  └─ open_hand → move_pregrasp → move_grasp
│  └─ grasp.close                   subskill：反馈闭合和记录锚点
│     └─ close_grasp
└─ pick.raise                       subskill：抬升并观察
   └─ lift → verify_lift
```

## 1. 先展开，再执行

内置定义在 `src/wuji/resources/skills.json`，本地新增定义保存在
`library/skills/<id>.json`，同 ID 的本地定义优先。定义包含 `id`、`level`、`version`、
参数默认值、步骤和后置检查。`requires` 说明起始状态依赖；它不是静态证明，
动作本身仍检查是否存在规划和抓取锚点。

```bash
python run_wuji.py skills
python run_wuji.py compile --task examples/hierarchical_pick_lift.json --output outputs/compiled
python run_wuji.py demo --task examples/hierarchical_pick_lift.json --develop-subskills --output outputs/hierarchy
```

`compile` 不连接设备，生成 `recipe.json`、`hierarchy.json` 和 `skill_tree.md`。
编译保留每一步的技能路径、版本和参数绑定，失败报告能指向某个子技能中的具体动作。
只检查未知动作、错误参数和循环调用等必要结构，不要求受限 AST 或固定层数。

调用格式：

```json
{"op": "call", "skill": "task.pick_lift", "args": {"height_m": 0.06}}
```

定义中的 `"$height_m"` 绑定参数；可以出现在嵌套的列表或字典中，不执行表达式。
CLI 也支持 `--skill <id> --params '<JSON object>'`。复杂参数直接放入任务 JSON
可避免终端引号差异。大任务既可调用已有技能，也可把需要调整的部分拆成更小的
调用和动作；修复提供者可返回新的层次配方。

## 2. 每层检查自己的结果

子技能结束时只运行声明的检查，不对每个动作重复拍摄。当前提供：

| 检查 | 检查范围 |
|---|---|
| `object_visible` | 已得到目标观测；可选 `max_age_s`，离线回放不按墙上时间过期 |
| `grasp_planned` | 已有候选；真机还要求通过当前几何筛选 |
| `tcp_at_grasp` | 当前 TCP 接近选定抓取姿态 |
| `tcp_at` | 当前 TCP 接近给定 `pose` |
| `grasp_anchored` | 闭合动作和观测/TCP 锚点存在，不证明持物稳定 |
| `lift_observed` | 本次锚点下的视觉抬升已通过，之后未释放或移动到其他位置 |

`verify_lift` 仍实际获取新图像。节点与任务的 `lift_observed` 复用这一证据，
不会为了每层节点再次运动或重复拍摄。顶层目标保存在 `goal_checks`；执行后按同一
条件检查。没有目标条件的技能可记录“执行完成”，报告审计不会把它标成完整任务验证。
为兼容旧的平面抓取放置配方，从 `verify_lift` 自动推断的目标只记录曾经观察到抬升
（`historical: true`），允许之后运输和放置。显式任务目标默认要求当前锚点仍有效。

`verified_mock`、`verified_real` 是具体节点检查的通过记录；其中 `real` 仅表示
来自真实运行，不能自动等同于摩擦稳定性、人工评测或完整任务的实物成功。
`physical_success` 仍保持 null。

## 3. 修复闭环

```text
执行 → 失败动作/节点 + 图像/反馈
     → diagnosis.json
     → 最小修改或重新观测建议
     → repair_proposal.json
     → 显式给出的额外尝试次数
     → 从已完成前缀之后继续
     → 原目标条件 + 新观测
     → repair_verification.json
```

默认 `--repair-attempts 0`：失败后保存诊断和建议，停止本次运行。
指定次数表示允许这些额外尝试，不额外反复请求确认。

```bash
# 纯离线示例：初始仅抬升 0.01 m，第二次只补足高度和重拍
python run_wuji.py demo --task examples/repair_short_lift.json --repair-attempts 1 --develop-subskills --output outputs/repair_demo

# 只重新计算报告中的测量与目标收据，不连接相机或机器人
python run_wuji.py verify --report outputs/repair_demo/report.json --output outputs/audit

# 为已记录失败生成可审阅建议，不恢复旧机器人的状态
python run_wuji.py repair --report outputs/repair_demo/attempt_01/report.json --output outputs/proposal
```

内置局部策略：

- 过期帧或目标暂时丢失：重拍失败动作，保留已经完成的运动。
- 候选不可用：在尚未开始抓取运动的位置增加搜索起点、改变随机种子。
- 合成演示抬升过短：补足局部高度，再用原阈值重拍验证。
- 真机抬升不明：只允许重新观测；不按合成演示规则继续抬升或重新抓取。
- 设备/接触停止、运动超时、人工中断：保留现场，交由工作站恢复。

恢复保留在同一个活 `Session` 中的手部规划、锚点和观测。独立启动的进程不会从
历史 JSON 猜测当前仍抓住物体。已完成前缀不能被改写后冒充执行过；跳过的节点
明确标记 `inherited`，引用之前的结果，不算第二次执行成功。

修复保持顶层目标条件，禁止通过降低验证阈值、删掉观察动作或修改运动限值来取得
成功。内置补丁只改规划/感知参数或未执行部分。这里的检查是为了让修复结果可解释，
不要求仿真通过、所有技能取得证书或多轮重放。

## 4. 发展和复用子技能

`--develop-subskills` 在每次尝试后提取已经完成的叶子节点，**即使大任务失败也保留
成功的子技能**。每份文件带参数、动作、局部检查、起始依赖、源节点/版本和运行证据。
修复后的连续抬升会合并成一个可调高度，而不是把“先失败再补救”的片段永久照搬。
规划子技能保留实际用过的搜索参数；重新调用时仍从新图像生成世界坐标目标。

```bash
# 从已有实验提取全部成功叶节点，不执行机器人动作
python run_wuji.py develop --report outputs/repair_demo/report.json

# 将一个成功子技能保存为便于引用的名字
python run_wuji.py develop --report outputs/repair_demo/report.json --node grasp.prepare --new-skill local.prepare

# 新任务调用它，再组合原有接近、闭合和抬升技能
python run_wuji.py demo --task examples/reuse_developed.json --output outputs/reuse
```

也可 `--node pick.acquire` 提取已完成的大节点，之后手工改写其步骤为更小的技能，
或让修复提供者提出新的分解。证据不足的整个父任务不会因为子节点完成而被提取为
“已完成任务”。相同内容累积多次证据；不同内容使用不同内容标识，显式命名冲突时
要求另选名字，避免悄悄覆盖旧技能。

自动发展不包含神经网络训练，也不会自动为所有任务选择新技能。本版完成的是
**从执行证据提取、参数化、归档和可再次调用**；新组合由任务配方或模型提供。
`pick.raise` 等子技能依赖已有抓取锚点，不能脱离起始状态单独执行。

## 5. 接入自己的模型修复器

`--repair-provider my_agent:repair` 调用受信任的 Python 函数：

```python
def repair(context):
    # context: recipe / report / diagnosis / config / observation / robot_state / attempt
    # 可调用自己的模型或根据反馈更细地分解失败技能。
    return {
        "recipe": revised_recipe,       # 原始层次配方或编译后配方
        "resume_from": failed_index,    # 实际完成前缀之后的位置
        "config_patch": {"planning": {"seeds": 12}},
        "mode": "local_replan",
        "automatic": True,
        "reason": "说明根据哪条反馈修改哪个子技能"
    }
```

修复器只负责返回方案，不应自己执行机器人动作。函数可以返回 null 表示使用内置
策略；异常会写入建议，保留原失败报告。它与自定义相机一样是本地受信任代码，
没有引入 Python 沙箱或强制外部模型服务。

## 6. 产物

```text
outputs/<run>/
  source_recipe.json
  skill_tree.md                  最终技能树及完成/失败状态
  report.json                    尝试链、修复验证、子技能发展汇总
  development.json              显式启用发展时生成
  attempt_01/
    recipe.json、hierarchy.json、config.json
    perception/、grasp_plan.json、grasp_preview.html
    trace.jsonl、report.json
    diagnosis.json、repair_proposal.json   失败时
  attempt_02/
    ...
    repair_verification.json      执行修复后生成
library/skills/<id>.json          可复用的本地子技能
```

`verify` 是基于保存测量的审计，不是独立物理重放。新一次运行调用技能可以做独立
复验，但不是每次学习的必备门槛。真机配置与恢复流程见
[HARDWARE_ZH.md](HARDWARE_ZH.md)。
