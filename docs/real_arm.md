# 真实 myCobot 280 M5 连接

## 设备

- USB：`1a86:55d4 QinHeng Electronics USB Single Serial`
- 串口：`/dev/ttyACM0`，波特率 `115200`（1 Mbps 会返回 -1）
- 权限：`sudo usermod -aG dialout $USER`，或临时 `sudo chmod 666 /dev/ttyACM0`

## 依赖

`pymycobot` + `pyserial`；本机可用源码方式：

```bash
git clone https://github.com/elephantrobotics/pymycobot /tmp/pylibs/pymycobot
git clone https://github.com/pyserial/pyserial /tmp/pylibs/pyserial
export PYTHONPATH=/tmp/pylibs/pymycobot:/tmp/pylibs/pyserial:$PYTHONPATH
```

## 读取与手动验证

```python
from pymycobot import MyCobot280
mc = MyCobot280('/dev/ttyACM0', 115200)
print(mc.get_angles())
print(mc.is_power_on(), mc.is_all_servo_enable())
print(mc.get_error_information())
```

注意：`send_angle(s)` 可能返回 `-1`，但机械臂实际会动；以 `get_angles()` 为准。
首次上电若关节超限（error=1），先 `clear_error_information()` 并把关节移回限位内。

## 仿真 → 实机同步

```bash
# dry-run，只看相对角度
python3 scripts/real_arm_bridge.py

# 真正驱动（建议先小 scale / 低速度）
python3 scripts/real_arm_bridge.py --execute --scale 0.2 --speed 10
```

映射方式：以实机当前角度为零点，

```text
target_real = start_real + scale * (sim_target - sim_home)
```

`sim_home = [0.2, 0.9, -1.3, 0.7, 0.4, 0.2] rad`。
当前桥每 20 条 `/arm/target` 发送一次（约 1 Hz），用于低速验证；
后续可提高到 5–10 Hz 以跟随波浪补偿。

## 启动归位（重要）

桥启动时会先归位，避免“锁在通电前随意姿态、只小幅抖动”：

1. `clear_error_information()`；
2. 以速度 15 发送 `--home`（默认 `sim`，即仿真 home 角度
   `[11.5, 51.6, -74.5, 40.1, 22.9, 11.5]°`）；
3. 等待各关节误差 < 5°，再开始 `/arm/target` 相对同步。

注意：归位可能是一次大幅度运动（例如 joint1 从 -164° 转到 +11°），
运行前务必清空机械臂周围空间，必要时用 `--home "0,0,0,0,0,0"` 指定更近的安全位。

## 通过 run_demo 一键启动

```bash
./run_demo.sh real_arm:=true                      # 默认 scale=0.2, speed=20
./run_demo.sh real_arm:=true real_arm_scale:=0.1 real_arm_speed:=10
./run_demo.sh real_arm:=true real_arm_home:=0,0,0,0,0,0
```

- 启动时自动归位，再跟随 `/arm/target`；
- 日志写入 `log/real_arm.log`；
- 退出时自动结束桥进程；
- 依赖首次准备：`./scripts/setup_real_arm_deps.sh`。

## 动作顿挫的处理

- 默认启用 `--fresh`（刷新模式）：固件只执行最新目标，不再排队等待；
- 桥内对关节目标做 0.5 一阶平滑；
- 发送频率由 `--divider` 控制，`4` ≈ 5 Hz，`2` ≈ 10 Hz；
- 实机测试建议：`--fresh --divider 2 --speed 50`，动作更连续；
- 退出时桥会把 fresh mode 复位为 0。

## 长期偏差闭环修正

桥在后台每 2 s 读取一次实机角度，与最后发送目标比较，缓慢积分偏移：

```text
offset += 0.02 * (cmd - actual)
```

- 修正量会叠加到下一条目标；
- 实测偏移收敛在 ±0.5° 内，最终实机与最后命令差 < 1°；
- 读取在独立线程，不阻塞主发送。

## 长期跟随：默认 1:1 映射

`real_arm_scale` 默认改为 **1.0**。早期用 0.2 时，仿真因船体漂移逐渐前探，
实机只跟随 20% 位移，看起来一直直立、与仿真差异越来越大。

1:1 长测（约 60 s）后，实机最终角度与仿真目标一致（前探、末端横置）：

```text
实机: [-25.4, 19.2, -69.1, 79.0, 58.4, 32.5]
仿真: [-25.5, 18.8, -64.1, 75.6, 57.2, 31.0]
```

若只想在 home 附近做小幅测试，再显式降低：

```bash
./run_demo.sh real_arm:=true real_arm_scale:=0.2
```

## 世界系简单路径

补偿节点支持在锁定点上叠加世界系路径：

```bash
./run_demo.sh real_arm:=true path_type:=square                    # 边长 12 cm
./run_demo.sh real_arm:=true path_type:=square path_side:=0.15 path_period:=24.0
```

实机使用 1:1 映射，会同时跟随正方形路径和波浪补偿。
