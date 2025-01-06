# NOTE: THIS DOESN'T WORK YET - STILL NEED TO WORK ON THIS PART OF THE TEMPLATE

# data "aws_sns_topic" "sns_topic" {
#   name = var.sns_topic_name
# }

# resource "aws_cloudwatch_metric_alarm" "success_metric_alarm" {
#   count                = var.environment == "prod" ? 1 : 0
#   alarm_name           = "${var.app_ident}-ecs-success-rate-alarm"
#   alarm_description    = "Alarm when ${var.app_ident} ECS tasks do not achieve 100% success"
#   comparison_operator  = "LessThanThreshold"
#   evaluation_periods   = var.alarm_after_n_minutes_without_success
#   datapoints_to_alarm  = var.alarm_after_n_minutes_without_success
#   threshold            = 100
#   alarm_actions        = [data.aws_sns_topic.sns_topic.arn]
#   treat_missing_data   = "breaching"

#   metric_query {
#     id          = "success_rate"
#     expression  = "100 - (failed / total) * 100"
#     label       = "Success Rate (%)"
#     return_data = true
#   }

#   metric_query {
#     id = "failed"
#     metric {
#       metric_name = "FailedTasks"
#       namespace   = "AWS/ECS"
#       period      = 60
#       stat        = "Sum"
#       dimensions = {
#         ClusterName = element(split("/", var.ecs_cluster_arn), 1)
#         ServiceName = var.app_ident # Replace with your service or task name
#       }
#     }
#   }

#   metric_query {
#     id = "total"
#     metric {
#       metric_name = "TaskCount"
#       namespace   = "AWS/ECS"
#       period      = 60
#       stat        = "Sum"
#       dimensions = {
#         ClusterName = element(split("/", var.ecs_cluster_arn), 1)
#         ServiceName = var.app_ident # Replace with your service or task name
#       }
#     }
#   }
# }

# resource "aws_cloudwatch_metric_alarm" "failure_metric_alarm" {
#   count                = var.environment == "prod" ? 1 : 0
#   alarm_name           = "${var.app_ident}-ecs-failure-alarm"
#   alarm_description    = "Alarm when ${var.app_ident} ECS tasks encounter any failures"
#   comparison_operator  = "GreaterThanThreshold"
#   evaluation_periods   = 1
#   datapoints_to_alarm  = 1
#   threshold            = 0
#   alarm_actions        = [data.aws_sns_topic.sns_topic.arn]
#   treat_missing_data   = "notBreaching"

#   metric_query {
#     id = "e1"
#     metric {
#       metric_name = "FailedTasks"
#       namespace   = "AWS/ECS"
#       period      = 60
#       stat        = "Sum"
#       dimensions = {
#         ClusterName = element(split("/", var.ecs_cluster_arn), 1)
#         ServiceName = var.app_ident # Replace with your service or task name
#       }
#     }
#     return_data = true
#   }
# }
