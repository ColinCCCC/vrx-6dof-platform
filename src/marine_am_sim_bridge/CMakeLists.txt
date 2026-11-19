cmake_minimum_required(VERSION 3.10.2)
project(marine_am_gz_bridge)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(gz-transport13 REQUIRED)
find_package(gz-msgs10 REQUIRED)


add_executable(wamv_pose_bridge src/wamv_pose_bridge.cpp)
target_link_libraries(wamv_pose_bridge
  gz-transport13::gz-transport13
  gz-msgs10::gz-msgs10
  tf2_ros::tf2_ros
  rclcpp::rclcpp
  ${geometry_msgs_TARGETS}
)

install(TARGETS wamv_pose_bridge
  DESTINATION lib/${PROJECT_NAME})


ament_package()
