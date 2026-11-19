import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    pkg_share = get_package_share_directory('vrx_6dof_platform')

    config = LaunchConfiguration('config')
    dry_run = LaunchConfiguration('dry_run')
    host = LaunchConfiguration('platform_host')
    port = LaunchConfiguration('platform_port')
    local_port = LaunchConfiguration('local_port')
    source_frame = LaunchConfiguration('source_frame')
    deck_frame = LaunchConfiguration('deck_frame')
    start_pose_bridge = LaunchConfiguration('start_pose_bridge')
    start_monitor = LaunchConfiguration('start_monitor')
    protocol = LaunchConfiguration('protocol')
    reference_mode = LaunchConfiguration('reference_mode')

    return LaunchDescription([
        DeclareLaunchArgument(
            'config',
            default_value=os.path.join(pkg_share, 'config', 'platform_bridge.yaml'),
            description='YAML 参数文件'),
        DeclareLaunchArgument(
            'dry_run', default_value='true',
            description='true：只打印报文，不发送 UDP'),
        DeclareLaunchArgument(
            'platform_host', default_value='192.168.1.88',
            description='平台控制板 IP'),
        DeclareLaunchArgument(
            'platform_port', default_value='8080',
            description='平台 UDP 端口'),
        DeclareLaunchArgument(
            'local_port', default_value='8080',
            description='本机绑定端口（接收平台自动回传）'),
        DeclareLaunchArgument(
            'source_frame', default_value='vrx_smoke_test',
            description='Gazebo world 帧名'),
        DeclareLaunchArgument(
            'deck_frame', default_value='marine_am_boat',
            description='WAM-V 位姿帧名'),
        DeclareLaunchArgument(
            'start_pose_bridge', default_value='true',
            description='是否同时启动 gz->TF 的 WAM-V 位姿桥接节点'),
        DeclareLaunchArgument(
            'reference_mode', default_value='detrend',
            description='参考位姿：initial 或 mean'),
        DeclareLaunchArgument(
            'protocol', default_value='fbfd32',
            description='平台协议：fbfd32（平台本体）或 washout64（洗出）'),
        DeclareLaunchArgument(
            'start_monitor', default_value='true',
            description='是否同时启动控制命令翻译监听'),

        Node(
            package='vrx_6dof_bridge',
            executable='wamv_pose_bridge',
            name='wamv_pose_bridge',
            output='screen',
            condition=IfCondition(start_pose_bridge),
            parameters=[{
                'world_frame': ParameterValue(source_frame, value_type=str),
                'model_name': ParameterValue(deck_frame, value_type=str),
                'publish_rate_hz': 100.0,
            }],
        ),

        Node(
            package='vrx_6dof_platform',
            executable='command_monitor',
            name='platform_command_monitor',
            output='screen',
            condition=IfCondition(start_monitor),
        ),
        Node(
            package='vrx_6dof_platform',
            executable='deck_pose_bridge',
            name='deck_pose_bridge',
            output='screen',
            parameters=[config, {
                'dry_run': ParameterValue(dry_run, value_type=bool),
                'platform_host': ParameterValue(host, value_type=str),
                'platform_port': ParameterValue(port, value_type=int),
                'local_port': ParameterValue(local_port, value_type=int),
                'source_frame': ParameterValue(source_frame, value_type=str),
                'deck_frame': ParameterValue(deck_frame, value_type=str),
                'reference_mode': ParameterValue(reference_mode, value_type=str),
            }],
        ),
    ])
