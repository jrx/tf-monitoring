# tf-monitoring

Root Terraform configuration that installs an observability stack on an
existing Amazon EKS cluster. State is stored in the `monitoring`
Terraform Cloud workspace under the `jrxhc` organization.

## What this deploys

Into a single Kubernetes namespace (default: `monitoring`):

| Component | Helm chart | Purpose |
|---|---|---|
| Prometheus Operator, Prometheus, Alertmanager, Grafana, node-exporter, kube-state-metrics | `prometheus-community/kube-prometheus-stack` | Metrics, dashboards, alerting |
| Loki (SingleBinary, filesystem) | `grafana/loki` | Log storage |
| Grafana Alloy | `grafana/alloy` | Pod-log collection, ships to Loki |

Grafana comes pre-configured with both Prometheus and Loki as datasources.
Alloy and Grafana both authenticate to Loki with tenant `1`.

### What Prometheus scrapes

In addition to everything `kube-prometheus-stack` discovers by default
(API server, kubelet, cAdvisor, kube-state-metrics, node-exporter, the
operator's own ServiceMonitors), this module declares two extra
`ServiceMonitor` resources in the kube-prometheus-stack values file:

| ServiceMonitor | Namespace | Selector | Port / Path |
|---|---|---|---|
| `n8n-main` | `n8n` | `name=n8n, instance=n8n` **and** `component` label absent | `http` (5678) `/metrics` |
| `keda` | `keda` | `app=keda-operator-metrics-apiserver` | `metrics` (8080) `/metrics` |

**Only `n8n-main` is scraped** — n8n mounts the Prometheus `/metrics`
route on the default server process only. The webhook-processor
(running `n8n webhook`) and the worker (running `n8n worker`) **do
not** expose `/metrics` even when `N8N_METRICS=true` is set on those
pods; the route is simply not registered by the n8n CLI in those
modes. Webhook-processor responds only on `/healthz`; the worker has
no HTTP server at all.

**`n8n-main` scrape is gated on an upstream change** — the n8n chart
does not set `N8N_METRICS=true` by default, so `/metrics` returns
HTTP 404 until the `n8n` Terraform Cloud workspace's Helm values
include:

```yaml
main:
  extraEnv:
    N8N_METRICS: "true"
```

Until then the scrape config is correct but produces zero samples.

## Prerequisites

- Terraform `>= 1.8.0`
- An existing EKS cluster, with its name exposed as the `cluster_name`
  output of the `n8n` Terraform Cloud workspace in the `jrxhc`
  organization. This module reads that workspace via
  `terraform_remote_state` — it does **not** create the cluster.
- AWS credentials with read access to the EKS cluster, and the `aws` CLI
  available in the Terraform run environment (used by the Kubernetes /
  Helm providers' `exec` auth blocks to call `aws eks get-token`).
  Terraform Cloud's default agent images include the `aws` CLI.

## Layout

```
.
├── versions.tf      # required_version + required_providers
├── providers.tf     # aws / kubernetes / helm providers (exec-auth)
├── data.tf          # remote_state + aws_eks_cluster lookup
├── main.tf          # namespace + 3 helm_releases
├── dashboards.tf    # ConfigMaps for every ./dashboards/*.json
├── variables.tf     # inputs (region, namespace, chart versions)
├── outputs.tf       # namespace, cluster, Grafana service/secret names
├── charts/
│   ├── kube-prometheus-stack.yaml
│   ├── loki.yaml
│   └── alloy.yaml
├── dashboards/
│   └── n8n-system-health.json
└── backend.hcl      # TFC remote backend config
```

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `aws_region` | AWS region of the target EKS cluster. | `string` | `eu-north-1` |
| `monitoring_namespace` | Namespace to install everything into. | `string` | `monitoring` |
| `kube_prometheus_stack_chart_version` | Pinned chart version. | `string` | `76.4.0` |
| `loki_chart_version` | Pinned chart version. | `string` | `7.0.0` |
| `alloy_chart_version` | Pinned chart version. | `string` | `1.8.1` |

Find newer chart versions with:

```sh
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana              https://grafana.github.io/helm-charts
helm repo update
helm search repo prometheus-community/kube-prometheus-stack --versions | head
helm search repo grafana/loki  --versions | head
helm search repo grafana/alloy --versions | head
```

## Outputs

| Name | Description |
|---|---|
| `monitoring_namespace` | Namespace where the stack is installed. |
| `eks_cluster_name` | Name of the targeted EKS cluster. |
| `grafana_service_name` | Service exposing Grafana inside the namespace. |
| `grafana_admin_secret_name` | Secret holding the Grafana admin credentials. |

## Usage

```sh
terraform init -backend-config=backend.hcl
terraform plan
terraform apply
```

### Access Grafana

```sh
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80

# Default admin password (from the chart):
kubectl -n monitoring get secret kube-prometheus-stack-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d ; echo
```

Open <http://localhost:3000> — username `admin`, password from the
secret above.

### Access Prometheus

The Prometheus UI (PromQL console, targets page, alerts page,
configuration view) is on the `kube-prometheus-stack-prometheus`
Service, port `9090`:

```sh
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090
```

Then open:

- <http://localhost:9090/targets> — scrape target health (look here to
  confirm `n8n-main` and `keda` are `UP`)
- <http://localhost:9090/graph> — PromQL console, e.g.
  `n8n_process_resident_memory_bytes` or `sum by (job) (up)`
- <http://localhost:9090/alerts> — alerts loaded from the chart's
  default rules
- <http://localhost:9090/config> — the fully-rendered scrape
  configuration the operator generated from the ServiceMonitor CRs

For day-to-day querying, prefer Grafana's *Explore* tab against the
pre-wired Prometheus datasource — the port-forward is mainly for
debugging discovery and scrape failures.

### Access Alertmanager

```sh
kubectl -n monitoring port-forward svc/kube-prometheus-stack-alertmanager 9093
```

Open <http://localhost:9093>.

## Grafana dashboards

Dashboards under `./dashboards/*.json` are auto-imported into Grafana.
Each file becomes a `ConfigMap` named `grafana-dashboard-<basename>` in
the `monitoring` namespace, labelled `grafana_dashboard=1`. The
k8s-sidecar bundled with `kube-prometheus-stack`'s Grafana watches for
ConfigMaps with that label and imports their JSON via Grafana's HTTP
API within a few seconds.

**To add a dashboard**

1. Drop a JSON file in `./dashboards/`. Filename without `.json`
   becomes the ConfigMap suffix; the dashboard's own `title` shows up
   in Grafana.
2. If the JSON was exported from grafana.com (and contains
   `"__inputs"` referencing `DS_PROMETHEUS`), replace **all** occurrences
   of `${DS_PROMETHEUS}` with `prometheus` (the datasource UID this
   stack uses by default). Otherwise every panel will render the error
   *"Datasource ${DS_PROMETHEUS} not found"*.
3. `terraform apply` — the sidecar will pick up the new ConfigMap and
   make the dashboard visible in Grafana under *Dashboards → General*
   within ~30s.

**To modify a dashboard**

Edit the JSON file directly and `terraform apply`. The sidecar
detects the ConfigMap update and re-imports. Round-tripping changes
from Grafana's UI back to the file is **not** automatic — use
Grafana's *Dashboard settings → JSON Model* to copy the new JSON back
into the file.

**Shipped dashboards**

| File | Source | What it shows |
|---|---|---|
| `n8n-system-health.json` | [grafana.com/dashboards/24474](https://grafana.com/grafana/dashboards/24474-n8n-system-health-overview/), revision 1, `${DS_PROMETHEUS}` substituted | n8n's Node.js runtime: CPU, memory, heap, event-loop latency, GC, file descriptors, instance metadata. Requires `N8N_METRICS=true` upstream. |

## Operational notes

- **CRDs**: the `kube-prometheus-stack` chart installs Prometheus
  Operator CRDs on first release, but Helm does **not** upgrade CRDs on
  subsequent chart upgrades. Bumping `kube_prometheus_stack_chart_version`
  across a CRD change requires manually applying the new CRDs first:
  ```sh
  kubectl apply --server-side -f \
    https://raw.githubusercontent.com/prometheus-community/helm-charts/kube-prometheus-stack-<version>/charts/kube-prometheus-stack/charts/crds/crds/
  ```
- **Loki durability**: SingleBinary + filesystem storage loses logs on
  pod restart. For anything beyond a sandbox cluster, switch
  `charts/loki.yaml` to S3 storage and the `SimpleScalable` deployment
  mode.
- **CRD scope**: Prometheus is configured with
  `serviceMonitorSelectorNilUsesHelmValues: false`, so any
  `ServiceMonitor` / `PodMonitor` / `PrometheusRule` in any namespace
  will be picked up.
- **Multi-tenancy**: Loki runs with `auth_enabled: true` and everything
  here uses tenant `1`. Consumers (Grafana, Alloy) send
  `X-Scope-OrgID: 1`.

## Chart version policy

All Helm chart versions are pinned via variables so applies are
reproducible. Bump deliberately after reviewing each chart's CHANGELOG —
in particular, `kube-prometheus-stack` major bumps occasionally rename
selectors or change CRD schemas.

## Cleanup

`terraform destroy` removes the namespace and all three Helm releases
cleanly. **However, Helm intentionally does not delete CRDs on uninstall**
(to prevent data loss across upgrades), so the following cluster-scoped
CRDs survive a destroy and need to be removed manually if you want a
pristine cluster:

```sh
kubectl delete crd \
  alertmanagerconfigs.monitoring.coreos.com \
  alertmanagers.monitoring.coreos.com \
  podlogs.monitoring.grafana.com \
  podmonitors.monitoring.coreos.com \
  probes.monitoring.coreos.com \
  prometheusagents.monitoring.coreos.com \
  prometheuses.monitoring.coreos.com \
  prometheusrules.monitoring.coreos.com \
  scrapeconfigs.monitoring.coreos.com \
  servicemonitors.monitoring.coreos.com \
  thanosrulers.monitoring.coreos.com
```

Leaving these CRDs in place is harmless on its own (no operator is
running to act on them), but a subsequent `terraform apply` will
**reuse** the existing CRDs rather than re-install them — which can be a
problem if `kube_prometheus_stack_chart_version` has moved across a CRD
schema break. When in doubt, purge before re-applying.
