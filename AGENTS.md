# tf-monitoring — AGENTS.md

Repo-local rules for agents working in this Terraform module. **Read this
before editing anything.** It captures non-obvious structural facts and
the specific mistakes a previous agent (this one) made.

The global rules in `~/.pi/agent/AGENTS.md` still apply on top of these.

---

## What this module does

Provisions the monitoring stack into an EKS cluster owned by the **`n8n`**
Terraform Cloud workspace:

- `kube-prometheus-stack` (Prometheus + Alertmanager + Grafana + node-exporter + kube-state-metrics)
- Loki (SingleBinary mode, filesystem storage — sandbox only; logs lost on pod restart)
- Grafana Alloy (replaces Promtail; tails pod logs to Loki)
- Two custom dashboard ConfigMaps under `./dashboards/`, loaded into Grafana
  by the chart's bundled `grafana-sc-dashboard` sidecar via the
  `grafana_dashboard=1` label.

State: TFC workspace **`jrxhc/monitoring`** (see `backend.hcl`).
Target cluster: `jrx-test` in `eu-north-1`. **Sandbox only** — see
`postgres-datasource.tf` security note about the n8n DB user with full
read/write on the n8n schema.

The `n8n` TFC workspace is the upstream source of truth for:
- `cluster_name` → `data.aws_eks_cluster.cluster`
- `rds_endpoint` → injected into the Postgres datasource values
- `db_password` → copied into `kubernetes_secret.n8n_postgres_grafana`

See `data.tf` and `postgres-datasource.tf`.

---

## Hard rules for dashboards under `./dashboards/`

These are conventions the module's design depends on. Past agents have
broken both of them. Don't.

### 1. Datasource UIDs are **hardcoded**, not template variables

The dashboards reference datasources by their literal UID:

- `"uid": "prometheus"` — provisioned by kube-prometheus-stack
- `"uid": "n8n-postgres"` — provisioned via `additionalDataSources` in
  `charts/kube-prometheus-stack.yaml`

**Do NOT** rewrite these to `"uid": "${datasource}"` and add a `datasource`
template variable to the dashboard. The chart provisions exactly one of
each type; the indirection adds nothing and breaks the convention
documented in the `dashboards.tf` header comment.

If a grafana.com-exported JSON contains `"${DS_PROMETHEUS}"` placeholders,
substitute them with the literal UID (`prometheus` or `n8n-postgres`)
**before committing**.

### 2. `"dataset": "n8n_data"` strings are **placeholders** — leave them in

`dashboards.tf` has a `replace()` in `local.dashboard_content`:

```hcl
replace(
  file(...),
  "\"dataset\": \"n8n_data\"",
  "\"dataset\": \"${var.n8n_db_name}\"",
)
```

`var.n8n_db_name` defaults to `n8n_enterprise`. At apply time, every
`"dataset": "n8n_data"` in committed JSON gets rewritten to
`"dataset": "n8n_enterprise"` (or whatever the var is set to).

That `n8n_data` literal is the **placeholder the substitution looks for**.
n8n's official dashboards on grafana.com hardcode `n8n_data`. Removing
those strings bypasses the substitution machinery — panels then fall back
to the datasource's default DB, which is strictly less robust than
explicit naming.

If you see `"dataset": "n8n_data"` in a panel target, **that is correct**.
The deployed ConfigMap will contain `"dataset": "n8n_enterprise"`.

### 3. Verify before claiming a panel is broken

A panel referencing `"dataset": "n8n_data"` looks broken on disk but is
not broken at runtime. Same for hardcoded UIDs that look like they should
fail import. Before "fixing" anything, check what the deployed JSON
actually contains:

```bash
kubectl -n monitoring get cm grafana-dashboard-<name> \
  -o jsonpath='{.data.<name>\.json}' | jq .
```

…or query Grafana directly (`/api/dashboards/uid/<uid>`, see below).

---

## Existing comments worth reading FIRST

Many gotchas are already documented inline. Read these before changing
anything they touch:

| File | Topics |
|---|---|
| `dashboards.tf` | Sidecar discovery (`grafana_dashboard=1` label), the `replace()` substitution, UID hardcoding convention. |
| `charts/kube-prometheus-stack.yaml` | `additionalServiceMonitors` must nest under `prometheus:` (chart 76→85 path change; top-level placement is silently accepted but renders nothing). `additionalDataSources` for Postgres needs `database` set in BOTH `database:` (legacy postgres plugin) AND `jsonData.database` (new `grafana-postgresql-datasource` plugin). The `N8N_POSTGRES_PASSWORD` env var resolves in provisioning YAML; `$__file{...}` does NOT. n8n-main is the only n8n pod that exposes `/metrics`; webhook/worker pods don't, even with `N8N_METRICS=true`. KEDA's `metrics` port (8080), not `https` (443). |
| `providers.tf` | Exec-based EKS auth (not `aws_eks_cluster_auth.token`) so 15-min token expiry doesn't kill multi-minute Helm installs. |
| `postgres-datasource.tf` | DB user is n8n's full read/write app user — sandbox only. Cross-namespace Secret copy. Why env-var interpolation, not `$__file{}`. |
| `main.tf` | Note that Helm only installs CRDs on first release; chart upgrades won't update them. |

---

## Operational quirks

### TFC remote backend

State is in TFC workspace `jrxhc/monitoring`. Implications:

- `terraform plan -out=<file>` is rejected by the remote backend. Use
  plain `terraform plan` (streams the remote run) then `terraform apply`.
- `terraform state` operations run remotely.
- An empty `terraform state list` on a fresh workspace is **normal**;
  it doesn't mean state was lost. The most recent commit
  (`Refactor/eks source from n8n workspace`) split monitoring out of the
  `n8n` workspace into this one, so early applies were greenfield.

### Verifying deployed dashboards through Grafana

```bash
PW=$(kubectl -n monitoring get secret kube-prometheus-stack-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d)

kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 13000:80 &
PF_PID=$!
sleep 4

curl -s -u "admin:$PW" 'http://localhost:13000/api/search?query=n8n&type=dash-db'
curl -s -u "admin:$PW" 'http://localhost:13000/api/dashboards/uid/<uid>'
curl -s -u "admin:$PW" 'http://localhost:13000/api/datasources'

kill $PF_PID
```

The admin password in the chart secret is correct out of the box; no
values override is set. If basic-auth returns 401, the most likely cause
is a bash variable scoping issue in your script (see below), not Grafana.

### No smoke tests in this repo

If the user asks about smoke tests, **don't fabricate a command**. There
are no `make smoke-test` / `npm run smoke-test` style targets here. Ask
where smoke tests live — they're more likely to belong to the `n8n`
workspace or a separate repo.

### Dashboards show "No data" until n8n exposes metrics

The ServiceMonitors are configured correctly, but n8n itself must be
started with `N8N_METRICS=true` (set in the n8n workspace's chart values)
for `/metrics` to return Prometheus-format output. Until then, expect
empty panels. Only n8n-main exposes the endpoint.

---

## Authoring dashboards

- Chart version `85.2.0` deploys Grafana 13.0.1, which uses
  `schemaVersion: 42` for new dashboards. Don't downgrade.
- Drop new `*.json` files into `./dashboards/`. `terraform apply` creates
  a matching ConfigMap (`grafana-dashboard-<basename>`) and the sidecar
  ingests it within seconds of creation.
- Sidecar pickup is observable in real time:
  ```bash
  kubectl -n monitoring logs deploy/kube-prometheus-stack-grafana \
    -c grafana-sc-dashboard -f
  ```

---

## Grafana variable gotcha: `allValue` bypasses formatters

When you set a custom `allValue` on a multi-select query variable, Grafana
substitutes that string **verbatim** into the query — the `:singlequote`,
`:csv`, `:doublequote`, etc. formatters are **ignored** for the All case.

For a Postgres `IN`-list filter that needs to work whether the user picks
"All" or specific items, the formatter-bypass means:

- `allValue: "__all__"` → Grafana sends bare `__all__` → Postgres parses
  it as a column reference → `ERROR: column "__all__" does not exist
  (SQLSTATE 42703)`.
- `allValue: "'__all__'"` (with embedded single quotes) → Grafana sends
  `'__all__'` literally → Postgres reads it as a string literal → works.

So: when using the OR-clause guard pattern

```sql
WHERE ('__all__' IN (${var:singlequote}) OR id IN (${var:singlequote}))
```

the matching `allValue` must be `"'__all__'"`, **including the quotes
in the JSON string**:

```json
{ "allValue": "'__all__'" }
```

This applies to any SQL filter using a query variable with a custom
`allValue`. PromQL doesn't have the same issue because it's not
identifier-vs-literal sensitive in the same way.

## Things to avoid (specific past mistakes)

- **Adding a `datasource` template variable to a dashboard.** See rule 1
  above.
- **Removing `"dataset": "n8n_data"` strings** from grafana.com-exported
  dashboards. See rule 2.
- **Asserting a panel is broken without checking the deployed JSON.**
  The Terraform substitution layer hides the on-disk text from what
  Grafana actually renders.
- **Trusting an empty `terraform state list` as "state was lost".** On
  a fresh workspace targeting a fresh cluster, 7 adds is the expected
  plan. Confirm with the user before assuming corruption.
- **Bash pitfall when port-forwarding from a script.** Writing
  `cmd1 && cmd2 && kubectl port-forward … & PF_PID=$!` on one logical
  `&&` chain backgrounds the **entire chain** into a subshell, so any
  `PW=$(…)` assignment in that chain stays in the subshell and the
  foreground curl runs with `PW=""`. Put `&` on its own line, with
  `PF_PID=$!` after a real newline. (Generic bash gotcha but it cost
  this agent ~20 minutes here.)
- **Passing markdown to `gh pr create --body "$(cat <<EOF…)"`.** The
  single-quoted heredoc protects the body during `cat`, but the outer
  `"$(…)"` re-introduces double-quoted parsing on cat's output. Any
  backticks inside the markdown then get evaluated as command
  substitution and the surrounding text disappears. Always use
  `gh pr create --body-file <path>` instead.
- **Setting a custom `allValue` without embedding quotes for SQL.**
  See the dedicated section above — Grafana bypasses formatters for
  `allValue`, so the value has to be SQL-safe as-is.
