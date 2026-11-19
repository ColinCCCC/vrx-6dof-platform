"""VRX 船体/水体仿真 + 全控平台桥接（不含机械臂）。"""
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, SetEnvironmentVariable
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    sim_dir = os.environ.get('MARINE_AM_SIM_DIR', '')
    worlds = os.path.join(sim_dir, 'worlds')
    models = os.path.join(worlds, 'models')
    world = LaunchConfiguration('world')
    config_file = LaunchConfiguration('config_file')
    headless = LaunchConfiguration('headless')
    paused = LaunchConfiguration('paused')
    dry_run = LaunchConfiguration('dry_run')
    start_monitor = LaunchConfiguration('start_monitor')
    platform_host = LaunchConfiguration('platform_host')
    platform_port = LaunchConfiguration('platform_port')
    source_frame = LaunchConfiguration('source_frame')
    deck_frame = LaunchConfiguration('deck_frame')
    reference_mode = LaunchConfiguration('reference_mode')

    resource = ':'.join([p for p in (worlds, models, os.environ.get('GZ_SIM_RESOURCE_PATH','')) if p])
    vrx = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(get_package_share_directory('vrx_gz'), 'launch', 'competition.launch.py')),
        launch_arguments={'world': world, 'config_file': config_file,
                          'headless': headless, 'paused': paused}.items())
    bridge = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(get_package_share_directory('marine_am_sim'), 'launch', 'platform_bridge.launch.py')),
        launch_arguments={'dry_run': dry_run, 'start_monitor': start_monitor,
                          'platform_host': platform_host, 'platform_port': platform_port,
                          'source_frame': source_frame, 'deck_frame': deck_frame,
                          'reference_mode': reference_mode}.items())
    return LaunchDescription([
        SetEnvironmentVariable('GZ_SIM_RESOURCE_PATH', resource),
        DeclareLaunchArgument('world', default_value=os.path.join(worlds, 'vrx_smoke_test.sdf')),
        DeclareLaunchArgument('config_file', default_value=os.path.join(sim_dir, 'config', 'no_robot.yaml')),
        DeclareLaunchArgument('headless', default_value='false'),
        DeclareLaunchArgument('paused', default_value='false'),
        DeclareLaunchArgument('dry_run', default_value='true'),
        DeclareLaunchArgument('start_monitor', default_value='true'),
        DeclareLaunchArgument('platform_host', default_value='192.168.1.88'),
        DeclareLaunchArgument('platform_port', default_value='8080'),
        DeclareLaunchArgument('source_frame', default_value='vrx_smoke_test'),
        DeclareLaunchArgument('deck_frame', default_value='marine_am_boat'),
        DeclareLaunchArgument('reference_mode', default_value='detrend'),
        vrx, bridge,
    ])
