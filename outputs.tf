output "monitoring_namespace" {
  description = "Kubernetes namespace where the observability stack is installed."
  value       = kubernetes_namespace.monitoring.metadata[0].name
}

output "eks_cluster_name" {
  description = "Name of the EKS cluster targeted by this stack."
  value       = data.aws_eks_cluster.cluster.name
}

# The default kube-prometheus-stack admin password is `prom-operator` and is
# stored in the Helm-generated Kubernetes Secret named below. Read with:
#   kubectl -n monitoring get secret kube-prometheus-stack-grafana \
#     -o jsonpath='{.data.admin-password}' | base64 -d
output "grafana_admin_secret_name" {
  description = "Kubernetes Secret holding the Grafana admin credentials (in monitoring_namespace)."
  value       = "kube-prometheus-stack-grafana"
}

# Port-forward Grafana with:
#   kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
output "grafana_service_name" {
  description = "Kubernetes Service exposing the Grafana UI (in monitoring_namespace)."
  value       = "kube-prometheus-stack-grafana"
}
