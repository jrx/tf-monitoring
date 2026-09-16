# tf-monitoring

Root Terraform configuration that installs an observability stack on an
existing Amazon EKS cluster. State is stored in the `monitoring`
Terraform Cloud workspace under the `jrxhc` organization.

## What this deploys

Into a single Kubernetes namespace (default: `monitoring`):

| Component | Helm chart | Purpose |
|---|---|---|
| Prometheus Operator, Prometheus, Alertmanager, Grafana, node-exporter, kube-state-metrics | `prometheus-community/kube-prometheus-stack` | Metrics, dashboards, alerting |
| Loki (Monolithic, filesystem on a gp3 PVC) | `grafana-community/loki` | Log storage (persistent) |
| Grafana Alloy | `grafana/alloy` | Pod-log collection + n8n Enterprise Log-Streaming syslog receiver; ships both to Loki |
| Jaeger (all-in-one, in-memory) | `jaegertracing/jaeger` | OpenTelemetry trace backend for n8n workflow/node spans; OTLP receiver + query UI; spanmetrics connector publishes RED metrics to Prometheus |

Grafana comes pre-configured with Prometheus, Loki, Jaeger, and the n8n RDS
Postgres database as datasources. Loki, Prometheus, Jaeger, and `n8n-postgres`
datasource UIDs are pinned literally so dashboards under `./dashboards/*.json`
can reference
them without indirection. Alloy and Grafana both authenticate to Loki with
tenant `1`.

### What Prometheus scrapes

In addition to everything `kube-prometheus-stack` discovers by default
(API server, kubelet, cAdvisor, kube-state-metrics, node-exporter, the
operator's own ServiceMonitors), this module declares three extra
`ServiceMonitor` resources in the kube-prometheus-stack values file,
plus one each from the PostgreSQL and Redis exporter charts:

| ServiceMonitor | Namespace | Selector | Port / Path |
|---|---|---|---|
| `n8n` | `n8n` | `name=n8n, instance=n8n` (all three role Services) | `http` (5678) `/metrics` |
| `keda` | `keda` | `app=keda-operator-metrics-apiserver` | `metrics` (8080) `/metrics` |
| `jaeger-spanmetrics` | `monitoring` | `name=jaeger, instance=jaeger` | `span-metrics` (8889) `/metrics` |
| `postgres-exporter-*` | `monitoring` | chart-managed (`exporters.tf`) | `http` (9187) `/metrics` |
| `redis-exporter-*` | `monitoring` | chart-managed (`exporters.tf`) | `redis-exporter` (9121) `/metrics` |

**All three n8n roles are scraped.** Main, webhook-processor and worker
all serve `/metrics` on 5678 once `N8N_METRICS=true` (verified live on
n8n 2.39.6). The n8n chart ships Services for main and
webhook-processor; the `tf-n8n` root module adds a matching `n8n-worker`
Service. The ServiceMonitor relabels every target to `job="n8n"` and
copies the pod's `app.kubernetes.io/component` label to `component`
(`main` / `webhook-processor` / `worker`). The n8n Monitoring Pack
dashboards depend on both labels.

**The producer side lives in `tf-n8n`.** `n8n_metrics_enabled = true`
sets `N8N_METRICS`, and `local.n8n_metrics_env` there turns on the
optional `N8N_METRICS_INCLUDE_*` families (DB pool, cache, execution
data, webhook and HTTP route histograms, event-bus workflow counters with
`workflow_id` / `workflow_name` labels, `n8n_workflow_info`, queue job
counts). Without those flags the pack dashboards show only the Node.js
runtime and Kubernetes panels.

### PostgreSQL and Redis exporters

`exporters.tf` installs `prometheus-community/prometheus-postgres-exporter`
and `prometheus-community/prometheus-redis-exporter` into `monitoring`:

- **postgres-exporter** connects to the n8n RDS instance with the same
  user and `n8n-postgres-grafana` Secret as the Grafana datasource
  (`sslmode=require`). Default collectors only; provides
  `pg_stat_activity_count`, `pg_stat_database_*`, `pg_stat_user_tables_*`.
  Same sandbox caveat as the datasource: this is n8n's application user.
- **redis-exporter** connects to the ElastiCache endpoint exported by the
  `n8n` workspace (`redis_endpoint` / `redis_port`; plaintext, no AUTH).
  `--check-single-keys` lists the five Bull state keys
  (`bull:jobs:{wait,active,delayed,failed,paused}`) so `redis_key_size`
  gives queue depth without scanning the keyspace. The n8n Terraform
  module's own optional redis-exporter stays off; it only watches two keys.

Because the Redis outputs are new, apply the `n8n` workspace before
planning this one, or the remote-state lookup fails.

**PgBouncer is not deployed.** The pack's "Database & Pooling" dashboard
has three PgBouncer panels; they are replaced by a text panel here rather
than left permanently empty.

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
│   ├── postgres-exporter.yaml # prometheus-postgres-exporter values
│   ├── redis-exporter.yaml    # prometheus-redis-exporter values
│   ├── loki.yaml
│   ├── alloy.yaml           # Helm values only — points at alloy-config CM
│   ├── alloy-config.river   # Alloy River pipeline (logs + syslog + PRI parsing)
│   └── jaeger.yaml          # Jaeger all-in-one, in-memory (OTLP -> query)
├── exporters.tf             # postgres-exporter + redis-exporter Helm releases
├── dashboards/
│   ├── n8n-baseline.json          # n8n Monitoring Pack (7 files), generated by
│   ├── n8n-business.json          #   import-monitoring-pack.py from the
│   ├── n8n-database.json          #   upstream portable JSON
│   ├── n8n-execdata.json
│   ├── n8n-golden.json
│   ├── n8n-queue.json
│   ├── n8n-saturation.json
│   ├── import-monitoring-pack.py
│   ├── n8n-governance.json
│   ├── build-governance-dashboard.py  # generator for n8n-governance.json
│   ├── n8n-audit-events.json
│   ├── build-audit-dashboard.py   # generator for n8n-audit-events.json
│   ├── upstream/                  # --portable builds of the two above, for the
│   │                              #   solutions-catalog pack; not deployed
│   ├── n8n-traces.json
│   └── build-traces-dashboard.py  # generator for n8n-traces.json
└── backend.hcl              # TFC remote backend config
```

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `aws_region` | AWS region of the target EKS cluster. | `string` | `eu-north-1` |
| `monitoring_namespace` | Namespace to install everything into. | `string` | `monitoring` |
| `kube_prometheus_stack_chart_version` | Pinned chart version. | `string` | `91.4.1` |
| `loki_chart_version` | Pinned chart version. | `string` | `18.13.1` |
| `alloy_chart_version` | Pinned chart version. | `string` | `1.12.1` |
| `jaeger_chart_version` | Pinned chart version. | `string` | `4.13.1` |
| `storage_class_name` | StorageClass for the Prometheus / Alertmanager / Loki PVCs. | `string` | `gp3` |
| `loki_retention_period` | Loki log retention (compactor deletes older chunks). `0` or a multiple of 24h. | `string` | `168h` |

Find newer chart versions with:

```sh
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana              https://grafana.github.io/helm-charts
helm repo add grafana-community    https://grafana-community.github.io/helm-charts
helm repo add jaegertracing        https://jaegertracing.github.io/helm-charts
helm repo update
helm search repo prometheus-community/kube-prometheus-stack --versions | head
helm search repo grafana-community/loki --versions | head
helm search repo grafana/alloy --versions | head
helm search repo jaegertracing/jaeger --versions | head
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
  confirm `n8n` (four endpoints across three roles), `keda`, and the two
  exporters are `UP`)
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
     export with their local database name baked in (the grafana.com n8n
     dashboards hardcode `"dataset": "n8n_data"`). Grafana's `grafana-postgresql-datasource`
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

**n8n Monitoring Pack**

Seven dashboards come from n8n's
[solutions-catalog](https://github.com/n8n-io/solutions-catalog/blob/main/validation/dashboards/n8n%20Monitoring%20Pack.md)
(`validation/dashboards/dashboards/portable/`). Do not edit those seven
JSON files by hand; `dashboards/import-monitoring-pack.py` regenerates
them from a clone of the upstream repo and applies the local adaptations
(literal `prometheus` UID instead of `$ds`, `job` / `ns` default to
`n8n`, PgBouncer panels replaced by a note, storage-mode panel shows the
active mode). To pick up upstream changes: clone the repo, bump
`UPSTREAM_COMMIT` in the script, run it, review the diff.

**Shipped dashboards**

| File | Source | Datasource | What it shows |
|---|---|---|---|
| `n8n-baseline.json` | n8n Monitoring Pack, via `dashboards/import-monitoring-pack.py` | Prometheus | One-page overview: executions/s by mode, failure ratio, p95 duration, slow webhooks, active workflows, queue backlog (n8n view), DB pool, event-loop lag, heap, restarts. |
| `n8n-golden.json` | n8n Monitoring Pack | Prometheus | Golden signals: HTTP ingest by role and status code, execution rate / failure ratio / quantiles, webhook latency, failed executions by workflow, multi-main leader count, seconds since last activity. |
| `n8n-business.json` | n8n Monitoring Pack | Prometheus | Per-workflow view: success rate and slowest workflows by name (joins `n8n_workflow_info`), executions/day projection, cache hit ratio. |
| `n8n-queue.json` | n8n Monitoring Pack | Prometheus (redis-exporter, kube-state-metrics) | Bull queue depth by key from Redis, failed jobs, completions/s, worker replicas and restarts, Redis commands/s. |
| `n8n-database.json` | n8n Monitoring Pack | Prometheus (postgres-exporter + n8n) | RDS transactions, connections by state, n8n pool utilisation / pending / acquire latency, cache hit ratio, deadlocks, dead tuples, insert rates. PgBouncer panels replaced by a note (not deployed). |
| `n8n-execdata.json` | n8n Monitoring Pack | Prometheus | Execution data reads/writes by mode and result, write bytes, latency and payload-size p95, unreadable bundles. Storage mode panel shows the active mode (`db` here) instead of asserting S3. |
| `n8n-saturation.json` | n8n Monitoring Pack | Prometheus (cAdvisor, kube-state-metrics, node-exporter) | Event-loop lag and heap by role, pod CPU / throttling / memory, OOMKills, restarts, replicas vs autoscaler, node CPU, pod age. |
| `n8n-governance.json` | hand-built via `dashboards/build-governance-dashboard.py` | Prometheus | Governance & quota, pack style: executions in range against a `$quota` textbox, lifetime production executions, daily volume by status, top workflows by executions / failures, stale active workflows (no success in 7d), zombie workflows (running, no `n8n.audit.workflow.updated` in 30d), instance totals. Needs `N8N_METRICS_INCLUDE_WORKFLOW_STATISTICS` plus the workflow-label flags; the 7d / 30d tables need matching retention. No SQL: the earlier Postgres version's project breakdown has no metric equivalent and was dropped. |
| `n8n-audit-events.json` | hand-built via `dashboards/build-audit-dashboard.py` | Loki | n8n Enterprise Log-Streaming audit-event view: severity / facility breakdown, audit events over time, identity & access, per-user attribution (top users by audit activity / by credential action, plus a `User` column on most-touched workflows), workflow lifecycle, credentials/API/MFA, execution-data reveals, raw event stream. Requires the syslog receiver (see below) and n8n Log Streaming configured to `alloy-syslog.monitoring.svc.cluster.local:1514`. |
| `n8n-traces.json` | hand-built via `dashboards/build-traces-dashboard.py` | Prometheus | RED metrics (rate / errors / p50-p95-p99 duration) derived from n8n's OpenTelemetry spans by the Jaeger spanmetrics connector, scraped into Prometheus. Per-workflow breakdown + span-type split. Requires OpenTelemetry tracing enabled (see below); empty until then. For individual trace search use Explore → Jaeger. |

> **Note on user attribution.** The per-user panels group by `payload__email`
> — the `| json`-flattened form of the audit event's `payload._email` field.
> For most events this is the **actor** (the user who performed the action),
> but some `n8n.audit.user.*` events (e.g. `user.deleted`, `user.invited`)
> may carry the **subject** user's email instead. Events with no
> `payload._email` (some service-account / public-API flows) are excluded
> from the "Top users by …" tables but still appear in the raw-stream panel,
> tagged `(no user)`.

## n8n PostgreSQL datasource

No shipped dashboard reads n8n's database any more (governance moved to
Prometheus). The `n8n-postgres` datasource stays provisioned for ad-hoc
queries in Explore, and its Secret is shared with the postgres-exporter.
Wiring:

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

### Span metrics & the RED dashboard

Individual traces live in Jaeger (Explore-oriented), but Jaeger's in-memory
store has no metrics backend — so trend dashboards come from a different path.
The Jaeger **spanmetrics connector** (`charts/jaeger.yaml`) derives RED
metrics from every span and its `prometheus` exporter publishes them on the
container's `:8889`, surfaced on the chart's `jaeger` Service as the
`span-metrics` port. The **`jaeger-spanmetrics` ServiceMonitor**
(`charts/kube-prometheus-stack.yaml`) scrapes that into the
kube-prometheus-stack Prometheus, and the **`n8n-traces` dashboard** renders
it (rate / error % / p50-p95-p99 latency, per-workflow breakdown).

Because the data lands in Prometheus, that dashboard reads the **prometheus**
datasource — not the Jaeger one. The emitted series are
`traces_span_metrics_calls_total` and
`traces_span_metrics_duration_milliseconds_*`, labelled `service_name`,
`span_name`, `status_code`, plus the n8n dimensions `n8n_workflow_name` and
`n8n_execution_status` (configured under `connectors.span_metrics.dimensions`
in `charts/jaeger.yaml` — keep that list short; each is a Prometheus label).
Select on `service_name`, not `job` (Prometheus rewrites the exposed `job` to
`exported_job` on scrape).

> ⚠️ **Cardinality.** `n8n_workflow_name` is an *unbounded* dimension — RED
> series scale as roughly `workflow_count × span_name × status_code`. That's
> fine for a sandbox, but on an instance with thousands of workflows it will
> inflate Prometheus series count. For large installs, drop
> `n8n.workflow.name` from the connector dimensions (fall back to per-workflow
> drill-down in Explore → Jaeger) or otherwise cap it.

Jaeger's own "Monitor" tab is intentionally not enabled (it would need
`metric_backends` + `monitor.menuEnabled`); the Grafana dashboard is the
consumer instead.

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
- **Persistence (PVCs)**: Prometheus (TSDB, 20Gi), Alertmanager (2Gi),
  and Loki (10Gi) each claim an EBS `gp3` PVC (`var.storage_class_name`),
  so metrics / silences / logs survive pod restarts and reschedules.
  `gp3` is `WaitForFirstConsumer`, so each volume binds in the AZ its pod
  lands in — no cross-AZ stranding for these single-replica workloads.
  This is durability, **not HA**: still one replica and one volume (one
  AZ) per component. Jaeger (in-memory traces) and Grafana (provisioned
  dashboards/datasources) remain ephemeral by design — the aggregate
  trace RED metrics persist in Prometheus regardless.
  > ⚠️ **Adding storage to an already-running stack**: a StatefulSet's
  > `volumeClaimTemplates` are immutable, so you can't `helm upgrade`
  > storage onto an existing Prometheus / Alertmanager / Loki. Delete the
  > StatefulSet first, orphaning its pods
  > (`kubectl -n monitoring delete sts <name> --cascade=orphan`), then
  > `terraform apply` — the operator/chart recreates it with the volume.
  > A greenfield apply is unaffected.
- **Loki retention**: the compactor runs with `retention_enabled` and
  deletes chunks older than `var.loki_retention_period` (default `168h`
  = 7d), keeping the 10Gi PVC bounded. Loki requires a
  `delete_request_store` when retention is on — set to `filesystem` to
  match the storage backend, with `working_directory` on the PVC
  (`/var/loki/compactor`). `retention_period` must be `0` (infinite) or a
  multiple of the 24h index period. Storage is still single-node
  filesystem (not S3); move to S3 + `SimpleScalable` for HA / high volume.
- **CRD scope**: Prometheus is configured with
  `serviceMonitorSelectorNilUsesHelmValues: false`, so any
  `ServiceMonitor` / `PodMonitor` / `PrometheusRule` in any namespace
  will be picked up.
- **Multi-tenancy**: Loki runs with `auth_enabled: true` and everything
  here uses tenant `1`. Consumers (Grafana, Alloy) send
  `X-Scope-OrgID: 1`.

## Chart version policy

Chart pins were checked against the official Helm repositories on 2026-09-16.
They deploy Prometheus Operator 0.94.0, Prometheus 3.14.0, Alertmanager 0.34.0,
Grafana 13.2.2, node-exporter 1.12.1, kube-state-metrics 2.20.0, Loki 3.7.7,
Alloy 1.19.2, and Jaeger 2.20.0 using the charts' bundled image versions.

The open-source Loki chart now uses the
[`grafana-community` repository](https://github.com/grafana-community/helm-charts/tree/main/charts/loki).
Its deployment mode is named `Monolithic`; values remain under `singleBinary`.
The filesystem PVC, retention, gateway address, and tenant configuration are unchanged.

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
