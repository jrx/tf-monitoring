resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = var.monitoring_namespace
  }
}

# Prometheus Operator + Grafana + Alertmanager + node-exporter + kube-state-metrics.
# Replaces the previous raw-manifest install via the abandoned gavinbunney/kubectl
# provider. CRDs are bundled with the chart; note that Helm only installs CRDs on
# the first release — chart upgrades will not update CRDs automatically.
resource "helm_release" "kube_prometheus_stack" {
  name       = "kube-prometheus-stack"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "kube-prometheus-stack"
  version    = var.kube_prometheus_stack_chart_version
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  values = [
    file("${path.module}/charts/kube-prometheus-stack.yaml")
  ]

  depends_on = [
    kubernetes_namespace.monitoring,
  ]
}

# Loki — SingleBinary mode, filesystem storage. Suitable for a sandbox cluster;
# logs are lost on pod restart. Move to object storage (S3) for durability.
resource "helm_release" "loki" {
  name       = "loki"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "loki"
  version    = var.loki_chart_version
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  values = [
    file("${path.module}/charts/loki.yaml")
  ]

  depends_on = [
    kubernetes_namespace.monitoring,
  ]
}

# Grafana Alloy — replaces Promtail (EOL Feb 2025). Tails pod logs via the
# Kubernetes API and forwards them to Loki.
resource "helm_release" "alloy" {
  name       = "alloy"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "alloy"
  version    = var.alloy_chart_version
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  values = [
    file("${path.module}/charts/alloy.yaml")
  ]

  depends_on = [
    helm_release.loki,
  ]
}
