# marine-am-sim

VRX 船体/水体仿真 + 南京全控六轴平台 FBFD32 桥接。独立于机械臂控制仓库。

```bash
colcon build --symlink-install
source install/setup.bash
export MARINE_AM_SIM_DIR=$PWD
ros2 launch marine_am_sim sim.launch.py
```

机械臂/补偿控制仓库通过 `MARINE_AM_SIM_DIR` 和 `run_demo.sh` 依赖本仓库。
