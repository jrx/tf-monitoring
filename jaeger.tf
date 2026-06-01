# Dedicated ClusterIP Service fronting the Jaeger all-in-one pod's OTLP
# receivers. n8n (Enterprise OpenTelemetry tracing) targets this Service by
# name:
#
#   jaeger-otlp.monitoring.svc.cluster.local:4318   (OTLP HTTP, protobuf)
#   jaeger-otlp.monitoring.svc.cluster.local:4317   (OTLP gRPC)
#
# n8n exports over OTLP HTTP and appends `/v1/traces`, so the n8n-side
# N8N_OTEL_EXPORTER_OTLP_ENDPOINT is the base URL:
#   http://jaeger-otlp.monitoring.svc.cluster.local:4318
#
# The chart's own `jaeger` Service already exposes 4317/4318 (alongside a pile
# of legacy agent/zipkin ports). This separate Service exists purely to give
# producers a stable, intention-revealing DNS name scoped to just OTLP —
# the same convention as alloy-syslog.tf.
resource "kubernetes_service" "jaeger_otlp" {
  metadata {
    name      = "jaeger-otlp"
    namespace = kubernetes_namespace.monitoring.metadata[0].name
    labels = {
      "app.kubernetes.io/name"      = "jaeger"
      "app.kubernetes.io/component" = "otlp-receiver"
      "app.kubernetes.io/part-of"   = "n8n-otel-tracing"
    }
  }

  spec {
    type = "ClusterIP"

    # Select the Jaeger all-in-one pod (labels set by the chart).
    selector = {
      "app.kubernetes.io/instance" = "jaeger"
      "app.kubernetes.io/name"     = "jaeger"
    }

    port {
      name        = "otlp-http"
      protocol    = "TCP"
      port        = 4318
      target_port = 4318
    }

    port {
      name        = "otlp-grpc"
      protocol    = "TCP"
      port        = 4317
      target_port = 4317
    }
  }

  depends_on = [helm_release.jaeger]
}
