from setuptools import setup, find_packages
package_name='vrx_6dof_platform'
setup(
    name=package_name, version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/'+package_name]),
        ('share/'+package_name, ['package.xml']),
        ('share/'+package_name+'/config', ['config/platform_bridge.yaml']),
        ('share/'+package_name+'/launch', ['launch/platform_bridge.launch.py','launch/sim.launch.py']),
    ],
    install_requires=['setuptools'], zip_safe=True,
    maintainer='Colin', maintainer_email='ColinCCCC@users.noreply.github.com',
    description='VRX simulation and platform bridge', license='Apache-2.0',
    entry_points={'console_scripts':[
        'deck_pose_bridge = vrx_6dof_platform.deck_pose_bridge:main',
        'command_monitor = vrx_6dof_platform.command_monitor:main',
    ]},
)
