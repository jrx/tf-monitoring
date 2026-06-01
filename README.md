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
| Grafana Alloy | `grafana/alloy` | Pod-log collection + n8n Enterprise Log-Streaming syslog receiver; ships both to Loki |
| Jaeger (all-in-one, in-memory) | `jaegertracing/jaeger` | OpenTelemetry trace backend for n8n workflow/node spans; OTLP receiver + query UI |

Grafana comes pre-configured with Prometheus, Loki, Jaeger, and the n8n RDS
Postgres database as datasources. Loki, Prometheus, Jaeger, and `n8n-postgres`
datasource UIDs are pinned literally so dashboards under `./dashboards/*.json`
can reference
them without indirection. Alloy and Grafana both authenticate to Loki with
tenant `1`.

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
├── versions.tf              # required_version + required_providers
├── providers.tf             # aws / kubernetes / helm providers (exec-auth)
├── data.tf                  # remote_state + aws_eks_cluster lookup
├── main.tf                  # namespace + 4 helm_releases + alloy-config CM
├── dashboards.tf            # ConfigMaps for every ./dashboards/*.json
├── postgres-datasource.tf   # n8n RDS connection + Grafana password Secret
├── alloy-syslog.tf          # ClusterIP Service fronting Alloy's syslog listener
├── jaeger.tf                # ClusterIP Service fronting Jaeger's OTLP receiver
├── variables.tf             # inputs (region, namespace, chart versions)
├── outputs.tf               # namespace, cluster, Grafana service/secret names
├── charts/
│   ├── kube-prometheus-stack.yaml
│   ├── loki.yaml
│   ├── alloy.yaml           # Helm values only — points at alloy-config CM
│   ├── alloy-config.river   # Alloy River pipeline (logs + syslog + PRI parsing)
│   └── jaeger.yaml          # Jaeger all-in-one, in-memory (OTLP -> query)
├── dashboards/
│   ├── n8n-system-health.json
│   ├── n8n-workflow-execution-analytics.json
│   ├── n8n-governance.json
│   ├── n8n-audit-events.json
│   └── build-audit-dashboard.py   # generator for n8n-audit-events.json
└── backend.hcl              # TFC remote backend config
```

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `aws_region` | AWS region of the target EKS cluster. | `string` | `eu-north-1` |
| `monitoring_namespace` | Namespace to install everything into. | `string` | `monitoring` |
| `kube_prometheus_stack_chart_version` | Pinned chart version. | `string` | `85.2.0` |
| `loki_chart_version` | Pinned chart version. | `string` | `7.0.0` |
| `alloy_chart_version` | Pinned chart version. | `string` | `1.8.1` |
| `jaeger_chart_version` | Pinned chart version. | `string` | `4.8.0` |

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
| `jaeger_otlp_http_endpoint` | In-cluster OTLP/HTTP base URL n8n exports traces to (append `/v1/traces`). |

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
2. If the JSON was exported from grafana.com:
   - Replace **all** occurrences of `${DS_PROMETHEUS}` with `prometheus`
     (the datasource UID this stack uses by default). Otherwise every
     panel will render *"Datasource ${DS_PROMETHEUS} not found"*.
   - Same for Postgres-backed dashboards: replace
     `${DS_GRAFANA-POSTGRESQL-DATASOURCE}` with `n8n-postgres`.
   - **Check for hardcoded `dataset` fields**: some dashboard authors
     export with their local database name baked in (e.g. the n8n
     workflow-execution-analytics dashboard hardcodes
     `"dataset": "n8n_data"`). Grafana's `grafana-postgresql-datasource`
     plugin honors the `dataset` field; when it doesn't match the
     datasource's database, panels show *"Configure a default database
     for the dashboard"*. `dashboards.tf` already substitutes
     `n8n_data` -> `var.n8n_db_name` at apply time; add more entries
     there for new dashboards that bring their own hardcoded names.
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

| File | Source | Datasource | What it shows |
|---|---|---|---|
| `n8n-system-health.json` | [grafana.com/dashboards/24474](https://grafana.com/grafana/dashboards/24474-n8n-system-health-overview/), rev 1, `${DS_PROMETHEUS}` → `prometheus` | Prometheus | n8n's Node.js runtime: CPU, memory, heap, event-loop latency, GC, file descriptors, instance metadata. Requires `N8N_METRICS=true` upstream. |
| `n8n-workflow-execution-analytics.json` | [grafana.com/dashboards/24475](https://grafana.com/grafana/dashboards/24475-n8n-workflow-execution-analytics/), rev 1, `${DS_GRAFANA-POSTGRESQL-DATASOURCE}` → `n8n-postgres` | PostgreSQL (n8n RDS) | Workflow execution analytics by querying the n8n DB directly (`execution_entity`, `workflow_entity`): success/error/crash counts, p50/p95/p99 duration, per-workflow stats, tag breakdowns. |
| `n8n-governance.json` | hand-built | PostgreSQL (n8n RDS) | Workflow & quota governance: active vs inactive workflows, ownership, tag coverage, recently changed workflows. |
| `n8n-audit-events.json` | hand-built via `dashboards/build-audit-dashboard.py` | Loki | n8n Enterprise Log-Streaming audit-event view: severity / facility breakdown, audit events over time, identity & access, per-user attribution (top users by audit activity / by credential action, plus a `User` column on most-touched workflows), workflow lifecycle, credentials/API/MFA, execution-data reveals, raw event stream. Requires the syslog receiver (see below) and n8n Log Streaming configured to `alloy-syslog.monitoring.svc.cluster.local:1514`. |

> **Note on user attribution.** The per-user panels group by `payload__email`
> — the `| json`-flattened form of the audit event's `payload._email` field.
> For most events this is the **actor** (the user who performed the action),
> but some `n8n.audit.user.*` events (e.g. `user.deleted`, `user.invited`)
> may carry the **subject** user's email instead. Events with no
> `payload._email` (some service-account / public-API flows) are excluded
> from the "Top users by …" tables but still appear in the raw-stream panel,
> tagged `(no user)`.

## n8n PostgreSQL datasource

The `n8n-workflow-execution-analytics` dashboard reads n8n's RDS
Postgres database directly via Grafana's built-in `postgres`
datasource plugin (datasource UID `n8n-postgres`). Wiring:

- `postgres-datasource.tf` reads the n8n Deployment's env to learn the
  RDS host / port / db / user, and copies n8n's DB password from the
  `n8n` Terraform Cloud workspace's `db_password` remote-state output
  into a `n8n-postgres-grafana` Secret in the `monitoring` namespace.
- `charts/kube-prometheus-stack.yaml` mounts that Secret read-only at
  `/etc/secrets/n8n-postgres/password` and references it from the
  `additionalDataSources` entry as `$__file{...}` — the password
  never appears as a pod env var or in the Grafana HTTP API responses.

> ⚠️ **Security note.** The Grafana datasource currently re-uses n8n's
> *application* DB user, which has full `OWNER` privileges on the n8n
> schema. Any Grafana user with Explore permissions can run
> `DELETE FROM execution_entity` (or worse) against the live n8n
> database. This is acceptable for the sandbox cluster but **not**
> for production. Before promoting:
>
> 1. Create a dedicated `grafana_readonly` Postgres role with only
>    `USAGE` on schema and `SELECT` on tables
>    (`GRANT USAGE ON SCHEMA public TO grafana_readonly;`
>    `GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_readonly;`
>    `ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO grafana_readonly;`).
> 2. Store its password in AWS Secrets Manager, owned by the `n8n`
>    workspace.
> 3. Update `postgres-datasource.tf` to read from that Secrets Manager
>    entry instead of `terraform_remote_state.n8n.outputs.db_password`.

## n8n Enterprise Log Streaming

The Alloy DaemonSet listens for RFC 5424 syslog over TCP on port 1514 in
every pod, fronted by a dedicated `alloy-syslog` ClusterIP Service. n8n's
Enterprise Log Streaming destination should be pointed at:

| | |
|---|---|
| Host | `alloy-syslog.monitoring.svc.cluster.local` |
| Port | `1514` |
| Protocol | TCP |
| Format | RFC 5424 |
| Recommended facility | `local0` |

The receiving pipeline lives in `charts/alloy-config.river`. It:

1. Captures the full syslog frame as the log line (`use_rfc5424_message = true`).
2. Pulls the PRI digits out via regex (`stage.regex`).
3. Derives `facility` and `severity` from PRI using sprig math + a
   numeric → RFC 5424 name lookup table (`stage.template`).
4. Promotes both to real Loki labels (`stage.labels`).
5. Rewrites the log line back to just the JSON message body so
   downstream LogQL `| json` queries keep working (`stage.output`).

**Why this dance instead of `loki.relabel` on `__syslog_message_*`:**
Alloy 1.16's `loki.source.syslog` strips every `__`-prefixed label at
the source boundary, so the next component never sees the auto-extracted
facility / severity. PRI-from-line is the only path that survives.

**Labels added to every syslog event:**

| Label | Cardinality | Example values |
|---|---|---|
| `source` | 1 | `n8n-log-streaming` |
| `facility` | 24 | `local0`, `user`, `daemon`, ... |
| `severity` | 8 | `emerg`, `err`, `warning`, `info`, `debug`, ... |

Sample LogQL queries (use Grafana's *Explore* tab against the Loki
datasource):

```logql
# All n8n audit events
{source="n8n-log-streaming"} | json | eventName=~`n8n\.audit\..*`

# Filter on severity
{source="n8n-log-streaming", severity=~"warning|err|crit|alert|emerg"}

# Cross-tab over the dashboard time range
sum by (severity, facility) (count_over_time({source="n8n-log-streaming"}[$__range]))

# Top users by audit activity (actor attribution; excludes events with no _email)
topk(20, sum by (payload__email, eventName) (count_over_time({source="n8n-log-streaming"} | json | eventName=~`n8n\.audit\..*` | payload__email != `` [$__range])))
```

**ConfigMap reload behaviour.** The Alloy chart's bundled
config-reloader sidecar is intentionally disabled. Instead, the
`helm_release.alloy` resource hashes `charts/alloy-config.river` and
stamps the sha1 onto `controller.podAnnotations.config.hash`, so any
edit to the River file rolls the DaemonSet on the next `terraform
apply`.

> ⚠️ **Network exposure note.** The cluster currently has no
> `NetworkPolicy`. Any pod in any namespace can reach
> `alloy-syslog:1514`. Acceptable for the sandbox; for production,
> restrict ingress to the `n8n` namespace with a NetworkPolicy and
> consider per-tenant routing inside the River pipeline.

## OpenTelemetry tracing

n8n can emit [OpenTelemetry](https://docs.n8n.io/hosting/logging-monitoring/opentelemetry/)
traces for workflow and node executions. This module runs the **trace
backend** (Jaeger all-in-one, in-memory) and exposes an OTLP endpoint; the
**n8n side** (turning tracing on) is configured in the `n8n` TFC workspace —
the same split as Enterprise Log Streaming above (this module runs the
receiver; n8n is pointed at it).

### What this module provides

| | |
|---|---|
| OTLP endpoint (HTTP) | `http://jaeger-otlp.monitoring.svc.cluster.local:4318` |
| OTLP endpoint (gRPC) | `jaeger-otlp.monitoring.svc.cluster.local:4317` |
| Terraform output | `jaeger_otlp_http_endpoint` (the HTTP base URL above) |
| Jaeger query UI | `kubectl -n monitoring port-forward svc/jaeger 16686` then <http://localhost:16686> |
| Grafana datasource | `Jaeger` (UID `jaeger`), with a coarse span → Loki-logs jump |

The dedicated `jaeger-otlp` Service (see `jaeger.tf`) is the intended producer
entrypoint. The chart's own `jaeger` Service also exposes 4317/4318 (plus a
pile of legacy agent/zipkin ports); consumers should target `jaeger-otlp` for
clarity.

### Turn tracing on in n8n (n8n TFC workspace)

n8n emits over **OTLP HTTP/protobuf** and appends `/v1/traces` to the
endpoint, so the endpoint is the **base URL**. The vars must be set on every
n8n instance you want traced — `main`, `worker`, **and** `webhook` (in
[queue mode](https://docs.n8n.io/hosting/scaling/queue-mode/) trace context
propagates between them, so all instances need them).

The n8n TFC module exposes typed inputs for this — prefer them over a
hand-rolled `extraEnv` map (the module fans the vars out to all instances):

```hcl
n8n_otel_enabled                = true
n8n_otel_exporter_otlp_endpoint = "http://jaeger-otlp.monitoring.svc.cluster.local:4318"
# Optional tuning (leave unset to use n8n's defaults):
# n8n_otel_traces_include_node_spans = false   # workflow-level spans only
# n8n_otel_traces_sample_rate        = 0.25    # sample a fraction on busy installs
```

If you're on a build of the n8n module without those variables, set the
underlying env vars directly instead (`N8N_OTEL_ENABLED="true"`,
`N8N_OTEL_EXPORTER_OTLP_ENDPOINT="http://jaeger-otlp.monitoring.svc.cluster.local:4318"`
on main/worker/webhook).

Restart n8n. Run a workflow, then look in Jaeger (service `n8n`) or Grafana's
*Explore* → Jaeger datasource. See the
[n8n OpenTelemetry env-var reference](https://docs.n8n.io/hosting/configuration/environment-variables/opentelemetry/)
for the full list.

> ⚠️ **Sandbox only.** Jaeger here uses **in-memory** storage (bounded ring
> buffer, `max_traces` in `charts/jaeger.yaml`) — traces are lost on pod
> restart, the same posture as Loki's filesystem storage. For durability,
> switch the `jaeger_storage` backend to Badger (add a PVC) or an external
> store (Elasticsearch / Cassandra) and review retention.
>
> ⚠️ **Network exposure.** As with `alloy-syslog`, there is no `NetworkPolicy`;
> any pod can reach `jaeger-otlp:4318`. Fine for the sandbox; restrict ingress
> to the `n8n` namespace before promoting.

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
