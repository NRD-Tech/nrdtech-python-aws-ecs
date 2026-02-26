# ECS Service failure alarm (optional; only when trigger_type = ecs_service and prod)
# NOTE: Template placeholder - wire SNS and dimensions for your service as needed.

resource "aws_sns_topic" "ecs_alerts" {
  count = var.trigger_type == "ecs_service" && var.environment == "prod" ? 1 : 0

  name = "${var.app_ident}-alerts"
}

resource "aws_cloudwatch_metric_alarm" "ecs_failure_alarm" {
  count = var.trigger_type == "ecs_service" && var.environment == "prod" ? 1 : 0

  alarm_name          = "${var.app_ident}-ecs-failure-alarm"
  alarm_description   = "Alarm when ${var.app_ident} ECS service tasks fail"
  comparison_operator  = "GreaterThanThreshold"
  evaluation_periods   = 1
  datapoints_to_alarm  = 1
  threshold            = 0
  alarm_actions        = [aws_sns_topic.ecs_alerts[0].arn]
  treat_missing_data   = "notBreaching"

  metric_query {
    id = "e1"
    metric {
      metric_name = "FailedTasks"
      namespace   = "AWS/ECS"
      period      = 60
      stat        = "Sum"
      dimensions = {
        ClusterName = element(split("/", aws_ecs_cluster.ecs.arn), 1)
        ServiceName = "${var.app_ident}-service"
      }
    }
    return_data = true
  }
}
