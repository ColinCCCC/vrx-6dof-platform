#!/usr/bin/env python3
"""持续监听平台控制命令报文，并翻译成可读文本。

默认监听 /deck_pose_bridge/platform_packet（64 字节原始报文），
按固定频率输出一行翻译后的命令；可配合 dry_run 使用，不依赖真实平台。
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import UInt8MultiArray

from marine_am_platform.protocol import (
    STATE_TEXT, decode_packet, decode_packet_fbfd32,
)


class CommandMonitor(Node):

    def __init__(self):
        super().__init__('platform_command_monitor')

        self.declare_parameter('packet_topic', '/deck_pose_bridge/platform_packet')
        self.declare_parameter('print_rate_hz', 5.0)
        self.declare_parameter('show_hex', False)

        topic = self.get_parameter('packet_topic').value
        rate = float(self.get_parameter('print_rate_hz').value)
        self.show_hex = bool(self.get_parameter('show_hex').value)

        self.latest = None
        self.count = 0

        self.create_subscription(UInt8MultiArray, topic, self._on_packet, 10)
        self.timer = self.create_timer(1.0 / max(1.0, rate), self._print)
        self.get_logger().info(
            f'监听 {topic}，按 {rate:.0f} Hz 输出翻译后的平台控制命令')

    def _on_packet(self, msg):
        self.latest = bytes(msg.data)
        self.count += 1

    def _print(self):
        if self.latest is None:
            self.get_logger().info('等待控制命令（/deck_pose_bridge/platform_packet）...')
            return

        if len(self.latest) == 32:
            try:
                d = decode_packet_fbfd32(self.latest)
            except ValueError as exc:
                self.get_logger().warn(str(exc))
                return
            f = d['fields']
            line = (
                f'#{self.count} FBFD32 | '
                f'x={f["x_mm"]:+.1f}mm y={f["y_mm"]:+.1f}mm z={f["z_mm"]:+.1f}mm | '
                f'俯仰={f["pitch_deg"]:+.2f}° 侧倾={f["roll_deg"]:+.2f}° '
                f'偏航={f["yaw_deg"]:+.2f}° | '
                f'幅度={d["amplitude"]} 速度={d["velocity"]} 柔度={d["smoothness"]} | '
                f'校验={"OK" if d["checksum_ok"] else "FAIL"}(0x{d["checksum"]:02X})'
            )
            if self.show_hex:
                line += ' | ' + ' '.join(f'{b:02X}' for b in self.latest)
            self.get_logger().info(line)
            return

        try:
            d = decode_packet(self.latest)
        except ValueError as exc:
            self.get_logger().warn(str(exc))
            return

        f = d['fields']
        state = STATE_TEXT.get(d['state'], f'未知({d["state"]})')
        washout = '采用' if d['washout'] else '不采用'
        shutdown = '主站关机' if d['shutdown'] else '无操作'
        line = (
            f'#{self.count} {state} | 洗出={washout} 开关机={shutdown} | '
            f'x={f["x_mm"]:+.1f}mm y={f["y_mm"]:+.1f}mm z={f["z_mm"]:+.1f}mm | '
            f'俯仰={f["pitch_deg"]:+.2f}° 侧倾={f["roll_deg"]:+.2f}° '
            f'偏航={f["yaw_deg"]:+.2f}° | '
            f'L={d["length"]} V={d["velocity"]} A={d["accelerate"]} | '
            f'校验={"OK" if d["checksum_ok"] else "FAIL"}'
            f'(0x{d["checksum"]:02X})'
        )
        if self.show_hex:
            line += ' | ' + ' '.join(f'{b:02X}' for b in self.latest)
        self.get_logger().info(line)


def main(args=None):
    rclpy.init(args=args)
    node = CommandMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            node.destroy_node()
            rclpy.shutdown()


if __name__ == '__main__':
    main()
