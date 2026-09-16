# Portable builds for upstream

Candidate additions to the n8n Monitoring Pack
(`n8n-io/solutions-catalog`, `validation/dashboards/dashboards/portable/`).
Generated, not hand-edited:

```sh
python3 dashboards/build-governance-dashboard.py --portable
python3 dashboards/build-audit-dashboard.py --portable
```

Not deployed by this module (`dashboards.tf` only reads `dashboards/*.json`).
The deployed twins in the parent directory are the same panels with this
module's hardcoded datasource UIDs.

Conventions matched to the pack's portable build: `id` stripped, uid
`n8n-<name>-portable`, title `n8n — <Name>`, schemaVersion 39, datasource
lifted into a variable, no credentials, `$job` where Prometheus is involved.

| File | Datasource | Variables | Prerequisites |
|---|---|---|---|
| `n8n-governance.json` | Prometheus (`$ds`) | `$job`, `$quota` textbox | `N8N_METRICS_INCLUDE_WORKFLOW_STATISTICS`, `_WORKFLOW_INFO`, `_MESSAGE_EVENT_BUS_METRICS`, `_WORKFLOW_ID_LABEL`, `_WORKFLOW_NAME_LABEL`; 7d / 30d retention for the stale / zombie tables |
| `n8n-audit-events.json` | Loki (`$loki`) | `$stream` textbox (label matchers for the log-streaming stream) | n8n Enterprise Log Streaming, syslog destination, receiver that ships the JSON event as the log line; `severity` / `facility` labels optional |

Known gaps against the earlier SQL-based governance dashboard: no executions
by project (n8n emits no project label) and no "last edited" timestamp
("not edited in 30d" is derived from the `n8n.audit.workflow.updated`
counter instead).
