# Grafana dashboards committed to ./dashboards/ are loaded into Grafana via
# the kube-prometheus-stack chart's bundled k8s-sidecar, which watches the
# monitoring namespace for ConfigMaps labeled `grafana_dashboard=1` and
# imports their JSON content into Grafana on a few-second discovery cycle.
#
# Drop a *.json file into ./dashboards/ and `terraform apply` will create a
# matching ConfigMap named `grafana-dashboard-<basename>`. Modify the file
# and re-apply to update the dashboard in place.
#
# Dashboards exported from grafana.com reference their Prometheus datasource
# as `${DS_PROMETHEUS}`; substitute those with the actual datasource UID
# (`prometheus`, set by the kube-prometheus-stack chart) before committing
# the JSON, otherwise panels render "Datasource ${DS_PROMETHEUS} not found".

locals {
  dashboard_dir = "${path.module}/dashboards"
  dashboards    = fileset(local.dashboard_dir, "*.json")

  # Apply environment-specific substitutions to every dashboard JSON at
  # apply time, so the files on disk stay close to their grafana.com
  # originals and so changes to vars (e.g. var.n8n_db_name) propagate
  # without re-editing JSON files.
  #
  # Currently handles:
  # - `"dataset": "n8n_data"` -> `"dataset": "<var.n8n_db_name>"`
  #   The n8n workflow-execution-analytics dashboard's author hardcoded
  #   the database name `n8n_data` in some panel targets. Grafana's new
  #   `grafana-postgresql-datasource` plugin honors that `dataset` field
  #   and prompts the user to "configure a default database" when it
  #   doesn't match the datasource's database.
  dashboard_content = {
    for f in local.dashboards :
    f => replace(
      file("${local.dashboard_dir}/${f}"),
      "\"dataset\": \"n8n_data\"",
      "\"dataset\": \"${var.n8n_db_name}\"",
    )
  }
}

resource "kubernetes_config_map" "grafana_dashboard" {
  for_each = local.dashboards

  metadata {
    name      = "grafana-dashboard-${trimsuffix(each.value, ".json")}"
    namespace = kubernetes_namespace.monitoring.metadata[0].name
    labels = {
      # Default sidecar.dashboards.label / labelValue in the chart.
      grafana_dashboard = "1"
    }
  }

  data = {
    (each.value) = local.dashboard_content[each.value]
  }

  depends_on = [helm_release.kube_prometheus_stack]
}
