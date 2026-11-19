"""平台协议编码与坐标换算（纯 Python，不依赖 ROS）。"""

import math
import struct

# ---------------------------------------------------------------- 坐标约定

# 机体坐标（REP-103：X 前 / Y 左 / Z 上）-> 平台坐标（X 右 / Y 前 / Z 上）
AXIS_MAP = (
    (0.0, -1.0, 0.0),
    (1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0),
)

# 平台控制指令（Byte56）位定义
BIT_WASHOUT = 0x20   # bit5：1 = 采用洗出算法
BIT_SHUTDOWN = 0x10  # bit4：1 = 主站关机
MASK_STATE = 0x03    # bits1-0：启停控制

STATE_IDLE = 0      # 待机（平台处于中位）
STATE_WORK = 1      # 工作（运行状态）
STATE_STOP = 2      # 停止（平台回到最低位）
STATE_PAUSE = 3     # 暂停（平台保持当前位置）

FIELDS = ('x_mm', 'y_mm', 'z_mm', 'pitch_deg', 'roll_deg', 'yaw_deg')


# ---------------------------------------------------------------- 数学工具

def quat_to_matrix(q):
    """四元数 (x, y, z, w) -> 3x3 旋转矩阵（行主序）。"""
    x, y, z, w = q
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return (
        (1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)),
        (2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)),
        (2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)),
    )


def matmul(a, b):
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
        for i in range(3)
    )


def transpose(a):
    return tuple(tuple(a[j][i] for j in range(3)) for i in range(3))


def mat_vec(a, v):
    return tuple(sum(a[i][k] * v[k] for k in range(3)) for i in range(3))


def euler_from_matrix(r):
    """按 R = Rz(yaw) Ry(roll) Rx(pitch) 提取角度（rad）。

    平台约定：pitch 绕 X（正=后仰），roll 绕 Y（正=右倾），yaw 绕 Z（正=左转）。
    """
    pitch = math.atan2(r[2][1], r[2][2])
    s = max(-1.0, min(1.0, -r[2][0]))
    roll = math.asin(s)
    yaw = math.atan2(r[1][0], r[0][0])
    return pitch, roll, yaw


def clamp(value, limit):
    return max(-limit, min(limit, value))


def matrix_to_quat(m):
    """3x3 旋转矩阵 -> 四元数 (x, y, z, w)，用于调试输出/低通重正交化。"""
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        w = 0.25 * s
        x = (m[2][1] - m[1][2]) / s
        y = (m[0][2] - m[2][0]) / s
        z = (m[1][0] - m[0][1]) / s
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        w = (m[2][1] - m[1][2]) / s
        x = 0.25 * s
        y = (m[0][1] + m[1][0]) / s
        z = (m[0][2] + m[2][0]) / s
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        w = (m[0][2] - m[2][0]) / s
        x = (m[0][1] + m[1][0]) / s
        y = 0.25 * s
        z = (m[1][2] + m[2][1]) / s
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
        w = (m[1][0] - m[0][1]) / s
        x = (m[0][2] + m[2][0]) / s
        y = (m[1][2] + m[2][1]) / s
        z = 0.25 * s
    return (x, y, z, w)


def normalize_quat(q):
    n = math.sqrt(sum(c * c for c in q))
    if n == 0.0:
        return (0.0, 0.0, 0.0, 1.0)
    return tuple(c / n for c in q)


def slerp(q0, q1, t):
    dot = sum(a * b for a, b in zip(q0, q1))
    if dot < 0.0:
        q1 = tuple(-c for c in q1)
        dot = -dot
    if dot > 0.9995:
        return normalize_quat(tuple(a + t * (b - a) for a, b in zip(q0, q1)))
    theta_0 = math.acos(max(-1.0, min(1.0, dot)))
    sin_theta_0 = math.sin(theta_0)
    s0 = math.sin((1.0 - t) * theta_0) / sin_theta_0
    s1 = math.sin(t * theta_0) / sin_theta_0
    return tuple(s0 * a + s1 * b for a, b in zip(q0, q1))


# ---------------------------------------------------------------- 报文编码

def build_packet(fields, state, washout=False, shutdown=False,
                 length=1, velocity=50, accelerate=10, timestamp_ms=None):
    """按 64 字节 WashOut64 协议（平台本体模式）打包。

    fields: dict(x_mm, y_mm, z_mm, pitch_deg, roll_deg, yaw_deg)
    """
    buf = bytearray(64)

    ts = timestamp_ms
    if ts is None:
        import time
        ts = int(time.time() * 1000)
    struct.pack_into('<I', buf, 0, ts & 0xFFFFFFFF)

    struct.pack_into('<f', buf, 4, float(fields['x_mm']))
    struct.pack_into('<f', buf, 8, float(fields['y_mm']))
    struct.pack_into('<f', buf, 12, float(fields['z_mm']))
    struct.pack_into('<f', buf, 16, float(fields['pitch_deg']))
    struct.pack_into('<f', buf, 20, float(fields['roll_deg']))
    struct.pack_into('<f', buf, 24, float(fields['yaw_deg']))
    # 洗出/模拟驾驶模式下使用：加速度与角速度
    struct.pack_into('<f', buf, 28, float(fields.get('acc_x', 0.0)))
    struct.pack_into('<f', buf, 32, float(fields.get('acc_y', 0.0)))
    struct.pack_into('<f', buf, 36, float(fields.get('acc_z', 0.0)))
    struct.pack_into('<f', buf, 40, float(fields.get('ang_x', 0.0)))
    struct.pack_into('<f', buf, 44, float(fields.get('ang_y', 0.0)))
    struct.pack_into('<f', buf, 48, float(fields.get('ang_z', 0.0)))

    ctrl = state & MASK_STATE
    if washout:
        ctrl |= BIT_WASHOUT
    if shutdown:
        ctrl |= BIT_SHUTDOWN
    buf[56] = ctrl
    buf[57] = length & 0xFF
    buf[58] = velocity & 0xFF
    buf[59] = accelerate & 0xFF
    buf[60] = 0x54  # 'T'
    buf[61] = 0x6F  # 'o'
    buf[62] = 0x43  # 'C'
    buf[63] = sum(buf[0:63]) & 0xFF
    return bytes(buf)


def hexdump(data):
    return ' '.join(f'{b:02X}' for b in data)




STATE_TEXT = {STATE_IDLE: '待机', STATE_WORK: '工作',
              STATE_STOP: '停止', STATE_PAUSE: '暂停'}


def decode_packet(packet):
    """解析 64 字节平台命令报文，返回字段字典（供监听/调试使用）。"""
    if len(packet) != 64:
        raise ValueError(f'报文长度应为 64，实际 {len(packet)}')
    fields = {
        'x_mm': struct.unpack_from('<f', packet, 4)[0],
        'y_mm': struct.unpack_from('<f', packet, 8)[0],
        'z_mm': struct.unpack_from('<f', packet, 12)[0],
        'pitch_deg': struct.unpack_from('<f', packet, 16)[0],
        'roll_deg': struct.unpack_from('<f', packet, 20)[0],
        'yaw_deg': struct.unpack_from('<f', packet, 24)[0],
    }
    ctrl = packet[56]
    checksum_ok = packet[63] == (sum(packet[0:63]) & 0xFF)
    return {
        'timestamp_ms': struct.unpack_from('<I', packet, 0)[0],
        'fields': fields,
        'control_byte': ctrl,
        'washout': bool(ctrl & BIT_WASHOUT),
        'shutdown': bool(ctrl & BIT_SHUTDOWN),
        'state': ctrl & MASK_STATE,
        'length': packet[57],
        'velocity': packet[58],
        'accelerate': packet[59],
        'fixed_ok': packet[60:63] == b'\x54\x6F\x43',
        'checksum': packet[63],
        'checksum_ok': checksum_ok,
    }


# ---------------------------------------------------------------- 上行回传帧

STATUS_HEADER = b'\xeb\x90\x11'
STATUS_TAIL = b'\xb0\xb1\xb2\xb3'


def decode_status(packet):
    """解析平台自动回传的 180 字节上行帧（字段含义待实验确认）。"""
    if len(packet) < 180:
        raise ValueError(f'回传帧长度应为 180，实际 {len(packet)}')
    speeds = [struct.unpack_from('<f', packet, o)[0]
              for o in range(32, 56, 4)]
    misc = [struct.unpack_from('<f', packet, o)[0]
            for o in range(88, 116, 4)]
    return {
        'valid': packet[:3] == STATUS_HEADER and packet[176:180] == STATUS_TAIL,
        'counter': struct.unpack_from('<I', packet, 172)[0],
        'speeds': speeds,
        'misc': misc,
        'marker': struct.unpack_from('<H', packet, 144)[0],
        'type': packet[152],
    }


# ---------------------------------------------------------------- FBFD32（平台本体/直接位姿）

FBFD32_HEADER = b'\xfb\xfd'


def build_packet_fbfd32(fields, amplitude=100, velocity=50,
                        smoothness=10, timestamp_ms=None):
    """32 字节 FBFD32 直接位姿协议（平台本体模式）。

    fields: x_mm, y_mm, z_mm, pitch_deg, roll_deg, yaw_deg
    """
    buf = bytearray(32)
    buf[0] = 0xFB
    buf[1] = 0xFD
    struct.pack_into('<f', buf, 2, float(fields['x_mm']))
    struct.pack_into('<f', buf, 6, float(fields['y_mm']))
    struct.pack_into('<f', buf, 10, float(fields['z_mm']))
    struct.pack_into('<f', buf, 14, float(fields['pitch_deg']))
    struct.pack_into('<f', buf, 18, float(fields['roll_deg']))
    struct.pack_into('<f', buf, 22, float(fields['yaw_deg']))
    buf[26] = amplitude & 0xFF
    buf[27] = velocity & 0xFF
    buf[28] = smoothness & 0xFF
    buf[29] = 0
    buf[30] = 0
    buf[31] = sum(buf[1:31]) & 0xFF
    return bytes(buf)


def decode_packet_fbfd32(packet):
    """解析 32 字节 FBFD32 平台本体报文。"""
    if len(packet) != 32:
        raise ValueError(f'FBFD32 报文长度应为 32，实际 {len(packet)}')
    fields = {
        'x_mm': struct.unpack_from('<f', packet, 2)[0],
        'y_mm': struct.unpack_from('<f', packet, 6)[0],
        'z_mm': struct.unpack_from('<f', packet, 10)[0],
        'pitch_deg': struct.unpack_from('<f', packet, 14)[0],
        'roll_deg': struct.unpack_from('<f', packet, 18)[0],
        'yaw_deg': struct.unpack_from('<f', packet, 22)[0],
    }
    return {
        'header_ok': packet[0:2] == FBFD32_HEADER,
        'fields': fields,
        'amplitude': packet[26],
        'velocity': packet[27],
        'smoothness': packet[28],
        'checksum': packet[31],
        'checksum_ok': packet[31] == (sum(packet[1:31]) & 0xFF),
    }
