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

  # The values file uses Terraform's templatefile() placeholders to inject
  # the n8n RDS connection details. Host comes from the n8n workspace's
  # rds_endpoint output; port/db/user come from variables in
  # postgres-datasource.tf.
  values = [
    templatefile("${path.module}/charts/kube-prometheus-stack.yaml", {
      n8n_db_host = data.terraform_remote_state.n8n.outputs.rds_endpoint
      n8n_db_port = var.n8n_db_port
      n8n_db_name = var.n8n_db_name
      n8n_db_user = var.n8n_db_user
    })
  ]

  depends_on = [
    kubernetes_namespace.monitoring,
    kubernetes_secret.n8n_postgres_grafana,
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

# Alloy's River config lives in its own file so the chart's Helm `tpl`
# pass doesn't try to interpret Alloy's `{{ ... }}` template syntax (used
# inside stage.template blocks to derive facility/severity labels from
# the syslog PRI field). The chart's configMap.create is set to false in
# charts/alloy.yaml and points at this resource instead.
resource "kubernetes_config_map" "alloy_config" {
  metadata {
    name      = "alloy-config"
    namespace = kubernetes_namespace.monitoring.metadata[0].name
    labels = {
      "app.kubernetes.io/name"       = "alloy"
      "app.kubernetes.io/instance"   = "alloy"
      "app.kubernetes.io/component"  = "config"
      "app.kubernetes.io/managed-by" = "Terraform"
    }
  }
  data = {
    "config.alloy" = file("${path.module}/charts/alloy-config.river")
  }
}

# Jaeger — all-in-one, in-memory (Jaeger v2). Receives OpenTelemetry traces
# from n8n over OTLP (4317 gRPC / 4318 HTTP) and serves the query API/UI on
# 16686. In-memory storage means traces are lost on pod restart — same
# sandbox posture as Loki's filesystem storage above. n8n is pointed at the
# dedicated `jaeger-otlp` Service (jaeger.tf); Grafana queries 16686 via the
# Jaeger datasource (uid: jaeger) provisioned in the kube-prometheus-stack
# values. Enabling tracing on n8n itself (N8N_OTEL_ENABLED + endpoint) is a
# change in the n8n TFC workspace, not here — see the README.
resource "helm_release" "jaeger" {
  name       = "jaeger"
  repository = "https://jaegertracing.github.io/helm-charts"
  chart      = "jaeger"
  version    = var.jaeger_chart_version
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  values = [
    file("${path.module}/charts/jaeger.yaml")
  ]

  # The Jaeger chart writes the pipeline to a `user-config` ConfigMap but puts
  # NO checksum annotation on the pod template, so editing charts/jaeger.yaml
  # updates the ConfigMap without rolling the Deployment — the running process
  # keeps the old config (same trap as Alloy below). Stamp a hash of the values
  # file into a throwaway env var to force a roll on config change. The
  # all-in-one component exposes `extraEnv` (it has no podAnnotations/podLabels).
  set {
    name  = "jaeger.extraEnv[0].name"
    value = "JAEGER_CONFIG_HASH"
  }
  set {
    name  = "jaeger.extraEnv[0].value"
    value = sha1(file("${path.module}/charts/jaeger.yaml"))
  }

  depends_on = [
    kubernetes_namespace.monitoring,
  ]
}

# Grafana Alloy — replaces Promtail (EOL Feb 2025). Tails pod logs via the
# Kubernetes API and forwards them to Loki, plus receives n8n Enterprise
# Log-Streaming syslog events on port 1514 (see charts/alloy-config.river).
resource "helm_release" "alloy" {
  name       = "alloy"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "alloy"
  version    = var.alloy_chart_version
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  values = [
    file("${path.module}/charts/alloy.yaml")
  ]

  # Roll the DaemonSet whenever the River config changes. The chart's
  # bundled config-reloader is disabled (see charts/alloy.yaml), so we
  # need to nudge it ourselves.
  #
  # NOTE: the chart reads pod annotations from `controller.podAnnotations`,
  # NOT top-level `podAnnotations`. Setting the top-level key is silently
  # accepted by Helm but never reaches the pod template, so the DaemonSet
  # would not roll on a standalone River edit.
  set {
    name  = "controller.podAnnotations.config\\.hash"
    value = sha1(kubernetes_config_map.alloy_config.data["config.alloy"])
  }

  depends_on = [
    helm_release.loki,
    kubernetes_config_map.alloy_config,
  ]
}
