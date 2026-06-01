variable "aws_region" {
  description = "AWS region of the target EKS cluster."
  type        = string
  default     = "eu-north-1"
}

variable "monitoring_namespace" {
  description = "Kubernetes namespace into which Prometheus, Grafana, Loki, and Alloy are installed."
  type        = string
  default     = "monitoring"
}

# Helm chart versions are pinned so applies are reproducible. Bump deliberately
# after reviewing the chart's CHANGELOG. Find the latest with:
#   helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
#   helm repo add grafana              https://grafana.github.io/helm-charts
#   helm search repo <repo>/<chart> --versions

variable "kube_prometheus_stack_chart_version" {
  description = "Pinned chart version for prometheus-community/kube-prometheus-stack."
  type        = string
  default     = "85.2.0"
}

variable "loki_chart_version" {
  description = "Pinned chart version for grafana/loki."
  type        = string
  default     = "7.0.0"
}

variable "alloy_chart_version" {
  description = "Pinned chart version for grafana/alloy."
  type        = string
  default     = "1.8.1"
}

variable "jaeger_chart_version" {
  description = "Pinned chart version for jaegertracing/jaeger (all-in-one, in-memory)."
  type        = string
  default     = "4.8.0"
}
