# myCobot 280 M5 模型资源

- 来源：Elephant Robotics 官方仓库
  <https://github.com/elephantrobotics/mycobot_ros2>
  路径：`mycobot_description/urdf/mycobot_280_m5/`
- 文件：`G_base.dae`、`joint1..7.dae` 及纹理 PNG。
- 用途：装配到 1 m 单体船上做机械臂仿真。
- 说明：上游仓库未声明统一许可证，使用前请遵循 Elephant Robotics 的授权与署名要求。
- 当前船模中机械臂各关节为 **fixed**（固定位姿）；后续会用 gz-sim 的
  `JointPositionController` 逐个关节驱动。
