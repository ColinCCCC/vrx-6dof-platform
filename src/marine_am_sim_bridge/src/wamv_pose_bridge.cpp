// 从 Gazebo transport 的 /world/<world>/pose/info 中提取 WAM-V 模型位姿，
// 以 ROS TF（world -> wamv）的形式广播出去，并在 Gazebo GUI 中标注追踪点。
//
// 注意：Gazebo 的 MarkerManager 是服务接口（/marker、/marker_array），
// 不是话题订阅；TEXT/AXIS 类型在 gz-gui 8 中不会显示，因此用
// 球体 + 前向指示线来标注。
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>

#include <geometry_msgs/msg/transform_stamped.hpp>
#include <rclcpp/rclcpp.hpp>
#include <tf2_ros/transform_broadcaster.h>

#include <gz/msgs/boolean.pb.h>
#include <gz/msgs/marker.pb.h>
#include <gz/msgs/marker_v.pb.h>
#include <gz/msgs/pose_v.pb.h>
#include <gz/math/Quaternion.hh>
#include <gz/transport/Node.hh>

class WamvPoseBridge : public rclcpp::Node
{
public:
  WamvPoseBridge() : rclcpp::Node("wamv_pose_bridge")
  {
    this->world_frame_ =
        this->declare_parameter<std::string>("world_frame", "vrx_smoke_test");
    this->model_name_ =
        this->declare_parameter<std::string>("model_name", "marine_am_boat");
    const std::string default_topic =
        "/world/" + this->world_frame_ + "/pose/info";
    const std::string topic =
        this->declare_parameter<std::string>("gz_pose_topic", default_topic);
    const double rate =
        this->declare_parameter<double>("publish_rate_hz", 100.0);
    this->marker_service_ =
        this->declare_parameter<std::string>("marker_service", "/marker");
    const double marker_rate =
        this->declare_parameter<double>("marker_rate_hz", 30.0);
    this->marker_scale_ =
        this->declare_parameter<double>("marker_scale", 0.08);
    this->marker_offset_z_ =
        this->declare_parameter<double>("marker_offset_z", 0.08);
    this->marker_arrow_length_ =
        this->declare_parameter<double>("marker_arrow_length", 0.30);
    this->marker_arrow_radius_ =
        this->declare_parameter<double>("marker_arrow_radius", 0.03);
    this->marker_stem_radius_ =
        this->declare_parameter<double>("marker_stem_radius", 0.02);

    this->broadcaster_ = std::make_unique<tf2_ros::TransformBroadcaster>(*this);

    if (!this->gz_node_.Subscribe(topic, &WamvPoseBridge::OnPoseV, this))
    {
      RCLCPP_ERROR(this->get_logger(), "无法订阅 Gazebo 话题: %s", topic.c_str());
    }
    else
    {
      RCLCPP_INFO(this->get_logger(), "订阅 Gazebo 话题: %s（模型 %s）",
                  topic.c_str(), this->model_name_.c_str());
    }

    const auto period_us = static_cast<int64_t>(1.0e6 / std::max(1.0, rate));
    this->timer_ = this->create_wall_timer(
        std::chrono::microseconds(period_us),
        std::bind(&WamvPoseBridge::Publish, this));

    const auto marker_period_us =
        static_cast<int64_t>(1.0e6 / std::max(1.0, marker_rate));
    this->marker_timer_ = this->create_wall_timer(
        std::chrono::microseconds(marker_period_us),
        std::bind(&WamvPoseBridge::PublishMarkers, this));
  }

private:
  void OnPoseV(const gz::msgs::Pose_V &_msg)
  {
    for (const auto &pose : _msg.pose())
    {
      if (pose.name() != this->model_name_)
      {
        continue;
      }
      std::lock_guard<std::mutex> lock(this->mutex_);
      this->position_ = pose.position();
      this->orientation_ = pose.orientation();
      this->stamp_sec_ = _msg.header().stamp().sec();
      this->stamp_nsec_ = _msg.header().stamp().nsec();
      this->has_pose_ = true;
      return;
    }
  }

  void Publish()
  {
    if (!this->has_pose_)
    {
      return;
    }

    gz::msgs::Vector3d pos;
    gz::msgs::Quaternion rot;
    int64_t sec = 0;
    uint32_t nsec = 0;
    {
      std::lock_guard<std::mutex> lock(this->mutex_);
      pos = this->position_;
      rot = this->orientation_;
      sec = this->stamp_sec_;
      nsec = this->stamp_nsec_;
    }

    geometry_msgs::msg::TransformStamped tf;
    tf.header.stamp = rclcpp::Time(
        static_cast<int32_t>(sec), nsec,
        this->get_clock()->get_clock_type());
    tf.header.frame_id = this->world_frame_;
    tf.child_frame_id = this->model_name_;
    tf.transform.translation.x = pos.x();
    tf.transform.translation.y = pos.y();
    tf.transform.translation.z = pos.z();
    tf.transform.rotation.x = rot.x();
    tf.transform.rotation.y = rot.y();
    tf.transform.rotation.z = rot.z();
    tf.transform.rotation.w = rot.w();
    this->broadcaster_->sendTransform(tf);
  }

  // 通过 MarkerManager 的 /marker_array 服务添加/更新标记：
  //   1) 橙色球体：被追踪的甲板点
  //   2) 黄色前向指示线：显示船体朝向
  void PublishMarkers()
  {
    if (!this->has_pose_)
    {
      return;
    }

    gz::msgs::Vector3d pos;
    gz::msgs::Quaternion rot;
    {
      std::lock_guard<std::mutex> lock(this->mutex_);
      pos = this->position_;
      rot = this->orientation_;
    }

    // 标记放到船体原点上方（甲板上方），避免被船体/水面遮挡
    gz::math::Quaterniond q(rot.w(), rot.x(), rot.y(), rot.z());
    const auto worldOffset = q.RotateVector(
        gz::math::Vector3d(0.0, 0.0, this->marker_offset_z_));
    gz::msgs::Vector3d topPos = pos;
    topPos.set_x(pos.x() + worldOffset.X());
    topPos.set_y(pos.y() + worldOffset.Y());
    topPos.set_z(pos.z() + worldOffset.Z());

    gz::msgs::Marker_V markers;

    auto *sphere = markers.add_marker();
    sphere->set_ns("marine_am_tracked");
    sphere->set_id(1);
    sphere->set_action(gz::msgs::Marker_Action_ADD_MODIFY);
    sphere->set_type(gz::msgs::Marker_Type_SPHERE);
    sphere->mutable_pose()->mutable_position()->CopyFrom(topPos);
    sphere->mutable_pose()->mutable_orientation()->CopyFrom(rot);
    sphere->mutable_scale()->set_x(this->marker_scale_);
    sphere->mutable_scale()->set_y(this->marker_scale_);
    sphere->mutable_scale()->set_z(this->marker_scale_);
    auto *mat = sphere->mutable_material();
    mat->mutable_ambient()->set_r(1.0f);
    mat->mutable_ambient()->set_g(0.2f);
    mat->mutable_ambient()->set_b(0.0f);
    mat->mutable_ambient()->set_a(1.0f);
    mat->mutable_diffuse()->set_r(1.0f);
    mat->mutable_diffuse()->set_g(0.35f);
    mat->mutable_diffuse()->set_b(0.0f);
    mat->mutable_diffuse()->set_a(1.0f);
    mat->mutable_emissive()->set_r(0.8f);
    mat->mutable_emissive()->set_g(0.2f);
    mat->mutable_emissive()->set_b(0.0f);
    mat->mutable_emissive()->set_a(1.0f);
    mat->set_lighting(false);

    // 前向指示：实体圆柱（沿船体 X 轴），比线段更醒目
    const double kHalfPi = 1.57079632679489661923;
    gz::math::Quaterniond qYaw90(0.0, kHalfPi, 0.0);
    gz::math::Quaterniond qHeading = q * qYaw90;
    const auto headingDir = q.RotateVector(gz::math::Vector3d(1.0, 0.0, 0.0));
    const double headingLen = this->marker_arrow_length_;
    gz::msgs::Vector3d headingPos = topPos;
    headingPos.set_x(topPos.x() + headingDir.X() * headingLen * 0.5);
    headingPos.set_y(topPos.y() + headingDir.Y() * headingLen * 0.5);
    headingPos.set_z(topPos.z() + headingDir.Z() * headingLen * 0.5);

    auto *heading = markers.add_marker();
    heading->set_ns("marine_am_tracked");
    heading->set_id(2);
    heading->set_action(gz::msgs::Marker_Action_ADD_MODIFY);
    heading->set_type(gz::msgs::Marker_Type_CYLINDER);
    heading->mutable_pose()->mutable_position()->CopyFrom(headingPos);
    heading->mutable_pose()->mutable_orientation()->set_x(qHeading.X());
    heading->mutable_pose()->mutable_orientation()->set_y(qHeading.Y());
    heading->mutable_pose()->mutable_orientation()->set_z(qHeading.Z());
    heading->mutable_pose()->mutable_orientation()->set_w(qHeading.W());
    heading->mutable_scale()->set_x(this->marker_arrow_radius_);
    heading->mutable_scale()->set_y(this->marker_arrow_radius_);
    heading->mutable_scale()->set_z(headingLen);
    auto *hmat = heading->mutable_material();
    hmat->mutable_diffuse()->set_r(1.0f);
    hmat->mutable_diffuse()->set_g(0.9f);
    hmat->mutable_diffuse()->set_b(0.1f);
    hmat->mutable_diffuse()->set_a(1.0f);
    hmat->mutable_emissive()->set_r(0.6f);
    hmat->mutable_emissive()->set_g(0.5f);
    hmat->mutable_emissive()->set_b(0.0f);
    hmat->mutable_emissive()->set_a(1.0f);
    hmat->set_lighting(false);

    // 垂线：实体圆柱，从追踪点连到上方球体（沿船体 Z 轴）
    const auto stemDir = q.RotateVector(gz::math::Vector3d(0.0, 0.0, 1.0));
    gz::msgs::Vector3d stemPos = pos;
    stemPos.set_x(pos.x() + stemDir.X() * this->marker_offset_z_ * 0.5);
    stemPos.set_y(pos.y() + stemDir.Y() * this->marker_offset_z_ * 0.5);
    stemPos.set_z(pos.z() + stemDir.Z() * this->marker_offset_z_ * 0.5);

    auto *stem = markers.add_marker();
    stem->set_ns("marine_am_tracked");
    stem->set_id(3);
    stem->set_action(gz::msgs::Marker_Action_ADD_MODIFY);
    stem->set_type(gz::msgs::Marker_Type_CYLINDER);
    stem->mutable_pose()->mutable_position()->CopyFrom(stemPos);
    stem->mutable_pose()->mutable_orientation()->CopyFrom(rot);
    stem->mutable_scale()->set_x(this->marker_stem_radius_);
    stem->mutable_scale()->set_y(this->marker_stem_radius_);
    stem->mutable_scale()->set_z(this->marker_offset_z_);
    auto *smat = stem->mutable_material();
    smat->mutable_diffuse()->set_r(0.2f);
    smat->mutable_diffuse()->set_g(0.6f);
    smat->mutable_diffuse()->set_b(1.0f);
    smat->mutable_diffuse()->set_a(1.0f);
    smat->mutable_emissive()->set_r(0.0f);
    smat->mutable_emissive()->set_g(0.2f);
    smat->mutable_emissive()->set_b(0.6f);
    smat->mutable_emissive()->set_a(1.0f);
    smat->set_lighting(false);

    this->gz_node_.Request(this->marker_service_ + "_array", markers,
                           &WamvPoseBridge::OnMarkerReply, this);
  }

  void OnMarkerReply(const gz::msgs::Boolean & /*_reply*/, const bool _result)
  {
    if (!_result && !this->marker_service_warned_)
    {
      RCLCPP_WARN_THROTTLE(
          this->get_logger(), *this->get_clock(), 5000,
          "Marker 服务 %s_array 不可用：GUI 未运行或 MarkerManager 未加载",
          this->marker_service_.c_str());
      this->marker_service_warned_ = true;
    }
  }

  std::string world_frame_;
  std::string model_name_;
  std::string marker_service_;
  double marker_scale_ = 0.08;
  double marker_offset_z_ = 0.08;
  double marker_arrow_length_ = 0.30;
  double marker_arrow_radius_ = 0.03;
  double marker_stem_radius_ = 0.02;
  std::unique_ptr<tf2_ros::TransformBroadcaster> broadcaster_;
  gz::transport::Node gz_node_;
  rclcpp::TimerBase::SharedPtr timer_;
  rclcpp::TimerBase::SharedPtr marker_timer_;

  std::mutex mutex_;
  gz::msgs::Vector3d position_;
  gz::msgs::Quaternion orientation_;
  int64_t stamp_sec_ = 0;
  uint32_t stamp_nsec_ = 0;
  bool has_pose_ = false;
  bool marker_service_warned_ = false;
};

int main(int argc, char **argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<WamvPoseBridge>();
  try
  {
    rclcpp::spin(node);
  }
  catch (const std::exception &e)
  {
    RCLCPP_ERROR(node->get_logger(), "节点异常: %s", e.what());
  }
  rclcpp::shutdown();
  return 0;
}
