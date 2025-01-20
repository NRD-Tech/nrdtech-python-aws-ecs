# NOTE: THIS DOESN'T WORK YET - STILL NEED TO WORK ON THIS PART OF THE TEMPLATE

# resource "aws_sns_topic" "sns_topic" {
#   name = "${var.app_ident}-alerts"
# }

# resource "aws_cloudwatch_metric_alarm" "failure_metric_alarm" {
#   count                = var.environment == "prod" ? 1 : 0
#   alarm_name           = "${var.app_ident}-ecs-failure-alarm"
#   alarm_description    = "Alarm when ${var.app_ident} ECS tasks encounter any failures"
#   comparison_operator  = "GreaterThanThreshold"
#   evaluation_periods   = 1
#   datapoints_to_alarm  = 1
#   threshold            = 0
#   alarm_actions        = [aws_sns_topic.sns_topic.arn]
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
