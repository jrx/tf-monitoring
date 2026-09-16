# Prometheus exporters for the two managed data stores behind n8n. n8n's own
# /metrics covers the application; these cover PostgreSQL (RDS) and Redis
# (ElastiCache) for the n8n Monitoring Pack "Database & Pooling" and
# "Queue & Workers" dashboards.
#
# Both charts create their own ServiceMonitor (serviceMonitor.enabled in the
# values files). Prometheus picks them up because
# serviceMonitorSelectorNilUsesHelmValues is false in
# charts/kube-prometheus-stack.yaml. The ServiceMonitor CRD must exist
# first, hence depends_on the kube-prometheus-stack release.
#
# Connection details come from the n8n workspace's remote state. The
# redis_endpoint / redis_port outputs are added in the same change as this
# file, so the n8n workspace must be applied before this one plans cleanly.

variable "postgres_exporter_chart_version" {
  description = "Pinned chart version for prometheus-community/prometheus-postgres-exporter."
  type        = string
  default     = "8.2.0"
}

variable "redis_exporter_chart_version" {
  description = "Pinned chart version for prometheus-community/prometheus-redis-exporter."
  type        = string
  default     = "6.31.1"
}

resource "helm_release" "postgres_exporter" {
  name       = "postgres-exporter"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "prometheus-postgres-exporter"
  version    = var.postgres_exporter_chart_version
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  values = [
    templatefile("${path.module}/charts/postgres-exporter.yaml", {
      n8n_db_host          = data.terraform_remote_state.n8n.outputs.rds_endpoint
      n8n_db_port          = var.n8n_db_port
      n8n_db_name          = var.n8n_db_name
      n8n_db_user          = var.n8n_db_user
      password_secret_name = kubernetes_secret.n8n_postgres_grafana.metadata[0].name
    })
  ]

  depends_on = [
    helm_release.kube_prometheus_stack,
  ]
}

resource "helm_release" "redis_exporter" {
  name       = "redis-exporter"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "prometheus-redis-exporter"
  version    = var.redis_exporter_chart_version
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  values = [
    templatefile("${path.module}/charts/redis-exporter.yaml", {
      redis_host = data.terraform_remote_state.n8n.outputs.redis_endpoint
      redis_port = data.terraform_remote_state.n8n.outputs.redis_port
    })
  ]

  depends_on = [
    helm_release.kube_prometheus_stack,
  ]
}
