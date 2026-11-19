#!/usr/bin/env python3
"""把 Gazebo/VRX 中 WAM-V 甲板的相对位姿，按南京全控 6 自由度平台的
WashOut64 UDP 协议（平台本体模式）发送给平台。

数据流：
    Gazebo 模型位姿 TF（world -> wamv）
      -> 相对参考位姿（启动瞬间位姿，或低通均值）
      -> 平台坐标系（X 右 / Y 前 / Z 上）
      -> 毫米 + 度，限幅
      -> 64 字节小端报文，UDP 发送

协议细节见 docs/platform_protocol.md。
"""

import math
import socket
from collections import deque

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time

import tf2_ros
from std_msgs.msg import Bool, Float64MultiArray, UInt8MultiArray

from marine_am_platform.protocol import (
    AXIS_MAP,
    decode_status,
    STATE_IDLE,
    STATE_PAUSE,
    STATE_WORK,
    build_packet,
    build_packet_fbfd32,
    clamp,
    euler_from_matrix,
    mat_vec,
    matmul,
    normalize_quat,
    quat_to_matrix,
    slerp,
    transpose,
)


class DeckPoseBridge(Node):

    def __init__(self):
        super().__init__('deck_pose_bridge')

        self.declare_parameter('source_frame', 'vrx_smoke_test')
        self.declare_parameter('deck_frame', 'wamv')
        self.declare_parameter('rate_hz', 50.0)

        self.declare_parameter('platform_host', '192.168.1.88')
        self.declare_parameter('platform_port', 8080)
        self.declare_parameter('local_port', 8080)
        self.declare_parameter('dry_run', True)
        self.declare_parameter('protocol', 'fbfd32')  # fbfd32 | washout64
        self.declare_parameter('amplitude', 100)
        self.declare_parameter('smoothness', 10)
        self.declare_parameter('washout_enabled', False)
        self.declare_parameter('shutdown', False)

        self.declare_parameter('reference_mode', 'detrend')  # initial | mean | detrend
        self.declare_parameter('detrend_window_s', 20.0)
        self.declare_parameter('detrend_sample_dt', 0.1)
        self.declare_parameter('mean_time_constant_s', 5.0)

        self.declare_parameter('translation_scale', 1.0)
        self.declare_parameter('rotation_scale', 1.0)
        self.declare_parameter('max_translation_mm', 100.0)
        self.declare_parameter('max_rotation_deg', 10.0)

        self.declare_parameter('length', 1)
        self.declare_parameter('velocity', 50)
        self.declare_parameter('accelerate', 10)

        self.declare_parameter('enable_motion', True)
        self.declare_parameter('stale_timeout_s', 0.3)
        self.declare_parameter('warmup_s', 8.0)

        self.source_frame = self.get_parameter('source_frame').value
        self.deck_frame = self.get_parameter('deck_frame').value
        rate = float(self.get_parameter('rate_hz').value)
        self.host = self.get_parameter('platform_host').value
        self.port = int(self.get_parameter('platform_port').value)
        self.local_port = int(self.get_parameter('local_port').value)
        self.dry_run = bool(self.get_parameter('dry_run').value)
        self.protocol = str(self.get_parameter('protocol').value)
        self.amplitude = int(self.get_parameter('amplitude').value)
        self.smoothness = int(self.get_parameter('smoothness').value)
        self.washout = bool(self.get_parameter('washout_enabled').value)
        self.shutdown = bool(self.get_parameter('shutdown').value)
        self.reference_mode = self.get_parameter('reference_mode').value
        self.detrend_window_s = float(self.get_parameter('detrend_window_s').value)
        self.detrend_sample_dt = float(self.get_parameter('detrend_sample_dt').value)
        self.mean_tau = float(self.get_parameter('mean_time_constant_s').value)
        self.translation_scale = float(self.get_parameter('translation_scale').value)
        self.rotation_scale = float(self.get_parameter('rotation_scale').value)
        self.max_translation_mm = float(self.get_parameter('max_translation_mm').value)
        self.max_rotation_deg = float(self.get_parameter('max_rotation_deg').value)
        self.length = int(self.get_parameter('length').value)
        self.velocity = int(self.get_parameter('velocity').value)
        self.accelerate = int(self.get_parameter('accelerate').value)
        self.enable_motion = bool(self.get_parameter('enable_motion').value)
        self.stale_timeout_s = float(self.get_parameter('stale_timeout_s').value)
        self.warmup_s = float(self.get_parameter('warmup_s').value)
        self.first_pose_time = None
        self.warmup_logged = False

        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        self.pub_cmd = self.create_publisher(Float64MultiArray, '~/platform_command', 10)
        self.pub_packet = self.create_publisher(UInt8MultiArray, '~/platform_packet', 10)
        self.pub_status = self.create_publisher(Float64MultiArray, '~/platform_status', 10)
        self.pub_status_raw = self.create_publisher(UInt8MultiArray, '~/platform_status_raw', 10)
        self.sub_enable = self.create_subscription(
            Bool, '~/enable', self._on_enable, 10)

        self.ref_p = None
        self.ref_q = None
        self.pose_hist = deque(maxlen=int(
            max(5.0, self.detrend_window_s) / max(0.02, self.detrend_sample_dt)) + 2)
        self.last_hist_t = -1e9
        self.ref_time = None
        self.last_valid_time = None
        self.last_fields = None
        self.last_log_time = 0.0
        self.enabled = self.enable_motion

        self.sock = None
        self.latest_status = None
        self.status_rx_count = 0
        self.last_status_log = 0.0
        if not self.dry_run:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self.sock.bind(('', self.local_port))
                self.sock.setblocking(False)
                self.get_logger().info(
                    f'UDP 目标 {self.host}:{self.port}，本机端口 {self.local_port}，'
                    f'{rate:.0f} Hz，平台本体模式')
            except OSError as exc:
                self.get_logger().warn(
                    f'绑定本机端口 {self.local_port} 失败（{exc}），'
                    '将以随机源端口发送，且无法接收自动回传')

        self.timer = self.create_timer(1.0 / max(1.0, rate), self._tick)
        self.status_timer = self.create_timer(0.2, self._publish_status)
        self.get_logger().info(
            f'订阅 TF {self.source_frame} -> {self.deck_frame}；'
            f'reference_mode={self.reference_mode}；dry_run={self.dry_run}')

    def _on_enable(self, msg):
        self.enabled = bool(msg.data)
        self.get_logger().info(f'平台运动使能: {self.enabled}')

    # -- 参考位姿 ------------------------------------------------------
    def _update_reference(self, p, q, now):
        if self.ref_p is None:
            self.ref_p = list(p)
            self.ref_q = tuple(q)
            self.ref_time = now
            self.last_hist_t = now
            self.pose_hist.append((now, tuple(p)))
            self.get_logger().info(
                f'捕获参考位姿: p={tuple(round(v, 4) for v in p)} '
                f'q={tuple(round(v, 4) for v in q)}')
            return

        dt = now - self.ref_time if now > self.ref_time else 0.0
        self.ref_time = now
        alpha = 1.0 - math.exp(-max(dt, 1e-3) / max(self.mean_tau, 1e-3))

        if self.reference_mode == 'mean':
            for i in range(3):
                self.ref_p[i] += alpha * (p[i] - self.ref_p[i])
            self.ref_q = slerp(self.ref_q, tuple(q), alpha)
            return

        if self.reference_mode == 'detrend':
            # 用滑动窗口的线性拟合估计并扣除漂移（斜坡），保留波浪振荡
            if now - self.last_hist_t >= self.detrend_sample_dt:
                self.last_hist_t = now
                self.pose_hist.append((now, tuple(p)))
            if len(self.pose_hist) >= 5:
                n = len(self.pose_hist)
                ts = [h[0] - now for h in self.pose_hist]
                mt = sum(ts) / n
                den = sum((t - mt) ** 2 for t in ts)
                for i in range(3):
                    ps = [h[1][i] for h in self.pose_hist]
                    mp = sum(ps) / n
                    slope = (sum((ts[k] - mt) * (ps[k] - mp) for k in range(n)) / den
                             if den > 1e-12 else 0.0)
                    self.ref_p[i] = mp + slope * (0.0 - mt)
            self.ref_q = slerp(self.ref_q, tuple(q), alpha)
            return
        # initial 模式：参考固定不变

    # -- 每周期 --------------------------------------------------------
    def _tick(self):
        now = self.get_clock().now().nanoseconds * 1e-9

        try:
            tf_msg = self.tf_buffer.lookup_transform(
                self.source_frame, self.deck_frame, Time(),
                timeout=Duration(seconds=0.05))
            self._handle_pose(tf_msg, now)
            return
        except (tf2_ros.LookupException,
                tf2_ros.ConnectivityException,
                tf2_ros.ExtrapolationException) as exc:
            if now - self.last_log_time > 2.0:
                self.get_logger().warn(
                    f'等待 TF {self.source_frame} -> {self.deck_frame}: {exc}')
                self.last_log_time = now

        # 失联超时：暂停（平台保持当前位置）
        stale = (self.last_valid_time is None
                 or now - self.last_valid_time > self.stale_timeout_s)
        if stale and self.last_fields is not None:
            self._send(self.last_fields, STATE_PAUSE)

    def _handle_pose(self, tf_msg, now):
        self.last_valid_time = now
        tr = tf_msg.transform
        p = (tr.translation.x, tr.translation.y, tr.translation.z)
        q = normalize_quat(
            (tr.rotation.x, tr.rotation.y, tr.rotation.z, tr.rotation.w))

        self._update_reference(p, q, now)
        if self.first_pose_time is None:
            self.first_pose_time = now
        if now - self.first_pose_time < self.warmup_s:
            if not self.warmup_logged:
                self.warmup_logged = True
                self.get_logger().info(
                    f'等待船体稳定 {self.warmup_s:.0f}s 后再开始发送平台命令')
            return
        if self.ref_p is None:
            return

        r_cur = quat_to_matrix(q)
        r_ref = quat_to_matrix(self.ref_q)

        # 位置：参考机体坐标系下的相对位移 -> 平台坐标
        dp = (p[0] - self.ref_p[0], p[1] - self.ref_p[1], p[2] - self.ref_p[2])
        dp_body = mat_vec(transpose(r_ref), dp)
        dp_platform = mat_vec(AXIS_MAP, dp_body)

        # 姿态：相对旋转 -> 平台坐标
        r_rel = matmul(transpose(r_ref), r_cur)
        r_plat = matmul(matmul(AXIS_MAP, r_rel), transpose(AXIS_MAP))
        pitch, roll, yaw = euler_from_matrix(r_plat)

        fields = {
            'x_mm': clamp(dp_platform[0] * 1000.0 * self.translation_scale,
                          self.max_translation_mm),
            'y_mm': clamp(dp_platform[1] * 1000.0 * self.translation_scale,
                          self.max_translation_mm),
            'z_mm': clamp(dp_platform[2] * 1000.0 * self.translation_scale,
                          self.max_translation_mm),
            'pitch_deg': clamp(math.degrees(pitch) * self.rotation_scale,
                               self.max_rotation_deg),
            'roll_deg': clamp(math.degrees(roll) * self.rotation_scale,
                              self.max_rotation_deg),
            'yaw_deg': clamp(math.degrees(yaw) * self.rotation_scale,
                             self.max_rotation_deg),
        }
        self.last_fields = fields

        state = STATE_WORK if self.enabled else STATE_IDLE
        self._send(fields, state)

    def _send(self, fields, state):
        if self.protocol == 'fbfd32':
            packet = build_packet_fbfd32(
                fields, amplitude=self.amplitude,
                velocity=self.velocity, smoothness=self.smoothness)
        else:
            packet = build_packet(
                fields, state,
                washout=self.washout, shutdown=self.shutdown,
                length=self.length, velocity=self.velocity,
                accelerate=self.accelerate)

        pkt_msg = UInt8MultiArray()
        pkt_msg.data = list(packet)
        self.pub_packet.publish(pkt_msg)

        now = self.get_clock().now().nanoseconds * 1e-9
        if self.dry_run:
            if now - self.last_log_time > 1.0:
                self.get_logger().info(
                    'DRY-RUN: ' + ', '.join(
                        f'{k}={v:+.2f}' for k, v in fields.items()) +
                    f' state={state}')
                self.last_log_time = now
        elif self.sock is not None:
            try:
                self.sock.sendto(packet, (self.host, self.port))
                self._drain_status()
            except OSError as exc:
                if now - self.last_log_time > 2.0:
                    self.get_logger().error(f'UDP 发送失败: {exc}')
                    self.last_log_time = now

        msg = Float64MultiArray()
        msg.data = [
            fields['x_mm'], fields['y_mm'], fields['z_mm'],
            fields['pitch_deg'], fields['roll_deg'], fields['yaw_deg'],
            float(state), 1.0,
        ]
        self.pub_cmd.publish(msg)


    # -- 接收平台自动回传 ---------------------------------------------
    def _drain_status(self):
        while True:
            try:
                data, _addr = self.sock.recvfrom(4096)
            except BlockingIOError:
                return
            except OSError:
                return
            if len(data) >= 180:
                self.latest_status = data
                self.status_rx_count += 1

    def _publish_status(self, now=None):
        if now is None:
            now = self.get_clock().now().nanoseconds * 1e-9
        if self.sock is not None:
            self._drain_status()
        if self.latest_status is None:
            return
        raw = self.latest_status
        msg_raw = UInt8MultiArray()
        msg_raw.data = list(raw)
        self.pub_status_raw.publish(msg_raw)
        try:
            info = decode_status(raw)
        except ValueError:
            return
        msg = Float64MultiArray()
        msg.data = [float(info['counter'])] + info['speeds'] + info['misc']
        self.pub_status.publish(msg)
        if now - self.last_status_log > 1.0:
            self.last_status_log = now
            self.get_logger().info(
                '平台回传: counter=%d 长度=[%s] 电流=[%s]' % (
                    info['counter'],
                    ', '.join(f'{v:.1f}' for v in info['speeds']),
                    ', '.join(f'{v:.0f}' for v in info['misc'])))


def main(args=None):
    rclpy.init(args=args)
    node = DeckPoseBridge()
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
