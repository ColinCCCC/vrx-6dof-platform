# vrx-6dof-platform

VRX 船体/水体仿真 + 南京全控六轴平台 FBFD32 桥接。独立于机械臂控制仓库。

```bash
colcon build --symlink-install
source install/setup.bash
export VRX_6DOF_DIR=$PWD
ros2 launch vrx_6dof_platform sim.launch.py
```

`vrx_gz` 仍作为外部依赖（可用 `vcs import src < dependencies.repos` 拉取）。

![平台闭环](docs/diagrams/node-topology.png)

![依赖关系](docs/diagrams/dependencies.png)

机械臂/补偿控制仓库通过 `VRX_6DOF_DIR` 和 `run_demo.sh` 依赖本仓库。
