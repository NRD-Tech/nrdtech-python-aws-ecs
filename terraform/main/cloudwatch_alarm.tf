# ECS Service failure alarm (optional; only when an API service trigger is active and ENVIRONMENT = prod)
# NOTE: Template placeholder - wire SNS subscriptions and dimensions for your service as needed.

resource "aws_sns_topic" "ecs_alerts" {
  count = local.ecs_api_service_enabled && var.ENVIRONMENT == "prod" ? 1 : 0

  name = "${var.APP_IDENT}-alerts"
}

resource "aws_cloudwatch_metric_alarm" "ecs_failure_alarm" {
  count = local.ecs_api_service_enabled && var.ENVIRONMENT == "prod" ? 1 : 0

  alarm_name          = "${var.APP_IDENT}-ecs-failure-alarm"
  alarm_description   = "Alarm when ${var.APP_IDENT} ECS service tasks fail"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  threshold           = 0
  alarm_actions       = [aws_sns_topic.ecs_alerts[0].arn]
  treat_missing_data  = "notBreaching"

  metric_query {
    id = "e1"
    metric {
      metric_name = "FailedTasks"
      namespace   = "AWS/ECS"
      period      = 60
      stat        = "Sum"
      dimensions = {
        ClusterName = element(split("/", aws_ecs_cluster.ecs.arn), 1)
        ServiceName = "${var.APP_IDENT}-service"
      }
    }
    return_data = true
  }
}

resource "aws_sns_topic_subscription" "ecs_alerts_email" {
  count = local.ecs_api_service_enabled && var.ENVIRONMENT == "prod" && var.ALERT_EMAIL != "" ? 1 : 0

  topic_arn = aws_sns_topic.ecs_alerts[0].arn
  protocol  = "email"
  endpoint  = var.ALERT_EMAIL
}
