# Dedicated ClusterIP Service in front of the Alloy DaemonSet's syslog
# listener. Producers (n8n main pods, when Enterprise Log Streaming is
# configured to a syslog destination) target this Service by name:
#
#   alloy-syslog.monitoring.svc.cluster.local:1514   (TCP, RFC 5424)
#
# kube-proxy round-robins TCP connections across all Alloy pods; every
# pod writes to the same single-tenant Loki, so any backend is fine.
#
# The Alloy chart's `extraPorts` (see charts/alloy.yaml) opens 1514 on
# the container and also exposes it on the chart's bundled `alloy`
# Service. This separate Service exists purely to give consumers a
# stable, intention-revealing DNS name decoupled from the metrics
# Service.
resource "kubernetes_service" "alloy_syslog" {
  metadata {
    name      = "alloy-syslog"
    namespace = kubernetes_namespace.monitoring.metadata[0].name
    labels = {
      "app.kubernetes.io/name"      = "alloy"
      "app.kubernetes.io/component" = "syslog-receiver"
      "app.kubernetes.io/part-of"   = "n8n-log-streaming"
    }
  }

  spec {
    type = "ClusterIP"

    # Select Alloy DaemonSet pods (labels set by the chart).
    selector = {
      "app.kubernetes.io/instance" = "alloy"
      "app.kubernetes.io/name"     = "alloy"
    }

    port {
      name        = "syslog-tcp"
      protocol    = "TCP"
      port        = 1514
      target_port = 1514
    }
  }

  depends_on = [helm_release.alloy]
}
