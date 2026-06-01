#!/usr/bin/env python3
"""Generate the n8n traces RED dashboard as deterministic JSON.

Output: dashboards/n8n-traces.json under this Terraform module.

Source data: RED metrics produced by the Jaeger spanmetrics connector
(see charts/jaeger.yaml), scraped from Jaeger's :8889 endpoint by the
`jaeger-spanmetrics` ServiceMonitor (charts/kube-prometheus-stack.yaml) into
the kube-prometheus-stack Prometheus. So this dashboard reads the PROMETHEUS
datasource (uid: prometheus), NOT the Jaeger datasource.

Verified metric schema (captured live from :8889):
  traces_span_metrics_calls_total{service_name, span_name, span_kind,
      status_code, n8n_workflow_name, n8n_execution_status}
  traces_span_metrics_duration_milliseconds_{bucket,sum,count}{...same...}
status_code values: STATUS_CODE_OK / STATUS_CODE_ERROR / STATUS_CODE_UNSET
We select on service_name (not job — Prometheus rewrites the exposed job to
exported_job on scrape).

Empty until n8n tracing is enabled in the n8n TFC workspace
(n8n_otel_enabled = true).
"""
import json

PROM = {"type": "prometheus", "uid": "prometheus"}

# Base label selector reused by every query. $service defaults to n8n;
# $workflow is a multi-select (regex OR) over n8n_workflow_name.
WF = 'service_name=~"$service", span_name="workflow.execute"'
WF_W = 'service_name=~"$service", span_name="workflow.execute", n8n_workflow_name=~"$workflow"'

NEXT_ID = 0
def nid():
    global NEXT_ID
    NEXT_ID += 1
    return NEXT_ID


def grid(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def row(title, y):
    return {"id": nid(), "type": "row", "title": title,
            "collapsed": False, "gridPos": grid(0, y, 24, 1), "panels": []}


def target(expr, legend=None, instant=False):
    t = {"datasource": PROM, "expr": expr, "refId": "A",
         "editorMode": "code", "range": not instant, "instant": instant}
    if legend is not None:
        t["legendFormat"] = legend
    return t


def stat(title, expr, x, y, w, h, *, unit="short", desc="", thresholds=None,
         color_mode="value", decimals=None):
    if thresholds is None:
        thresholds = {"mode": "absolute", "steps": [{"color": "blue", "value": None}]}
    defaults = {"unit": unit, "thresholds": thresholds,
                "color": {"mode": "thresholds"}, "mappings": []}
    if decimals is not None:
        defaults["decimals"] = decimals
    return {
        "id": nid(), "type": "stat", "title": title, "description": desc,
        "datasource": PROM, "gridPos": grid(x, y, w, h),
        "targets": [target(expr, instant=False)],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": color_mode, "graphMode": "area", "textMode": "auto",
            "justifyMode": "auto",
        },
        "pluginVersion": "12.3.0", "transparent": True,
    }


def _seq_refids(targets):
    """Grafana requires a unique refId per query in a panel; assign A, B, C…
    in order. The table's organize transform relies on this (Value #A / #B)."""
    for i, t in enumerate(targets):
        t["refId"] = chr(ord("A") + i)
    return targets


def timeseries(title, targets, x, y, w, h, *, unit="short", desc="",
               stack=False, fill=10, overrides=None):
    targets = _seq_refids(targets)
    return {
        "id": nid(), "type": "timeseries", "title": title, "description": desc,
        "datasource": PROM, "gridPos": grid(x, y, w, h),
        "targets": targets,
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "custom": {
                    "drawStyle": "line", "lineInterpolation": "smooth",
                    "lineWidth": 2, "fillOpacity": fill, "showPoints": "never",
                    "spanNulls": False, "axisPlacement": "auto",
                    "stacking": {"mode": "normal" if stack else "none", "group": "A"},
                },
                "color": {"mode": "palette-classic"},
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
            },
            "overrides": overrides or [],
        },
        "options": {
            "legend": {"calcs": ["last", "max"], "displayMode": "table",
                       "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
        "pluginVersion": "12.3.0", "transparent": True,
    }


def table(title, targets, x, y, w, h, *, desc="", transformations=None,
          overrides=None, sort_by=None):
    targets = _seq_refids(targets)
    # Table panels render instant vectors most reliably with format=table
    # (drops the Time column at source; the merge/organize transform then
    # surfaces label columns + Value #A/#B cleanly).
    for t in targets:
        t["format"] = "table"
    return {
        "id": nid(), "type": "table", "title": title, "description": desc,
        "datasource": PROM, "gridPos": grid(x, y, w, h),
        "targets": targets,
        "fieldConfig": {
            "defaults": {
                "custom": {"align": "left", "cellOptions": {"type": "auto"},
                           "filterable": True, "inspect": False},
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
            },
            "overrides": overrides or [],
        },
        "options": {"cellHeight": "sm", "showHeader": True,
                    "sortBy": [{"displayName": sort_by, "desc": True}] if sort_by else []},
        "transformations": transformations or [],
        "pluginVersion": "12.3.0", "transparent": True,
    }


ERR = 'status_code="STATUS_CODE_ERROR"'
panels = []

# ── Row 1: workflow RED overview ──────────────────────────────────────────
panels.append(row("Workflow execution traces — RED overview", 0))
panels.append(stat(
    "Exec rate", f'sum(rate(traces_span_metrics_calls_total{{{WF_W}}}[$__rate_interval]))',
    0, 1, 5, 4, unit="reqps", decimals=2,
    desc="workflow.execute spans/sec across the selected workflows (the n8n execution rate as seen by tracing).",
))
panels.append(stat(
    "Error rate",
    f'100 * sum(rate(traces_span_metrics_calls_total{{{WF_W}, {ERR}}}[$__rate_interval])) '
    f'/ clamp_min(sum(rate(traces_span_metrics_calls_total{{{WF_W}}}[$__rate_interval])), 1e-9)',
    5, 1, 5, 4, unit="percent", decimals=2, color_mode="background",
    thresholds={"mode": "absolute", "steps": [
        {"color": "green", "value": None}, {"color": "yellow", "value": 1},
        {"color": "orange", "value": 5}, {"color": "red", "value": 10}]},
    desc="Percentage of workflow.execute spans with status_code=ERROR over the rate window.",
))
panels.append(stat(
    "p95 duration",
    f'histogram_quantile(0.95, sum by (le) (rate(traces_span_metrics_duration_milliseconds_bucket{{{WF_W}}}[$__rate_interval])))',
    10, 1, 5, 4, unit="ms", decimals=0, color_mode="background",
    thresholds={"mode": "absolute", "steps": [
        {"color": "green", "value": None}, {"color": "yellow", "value": 1000},
        {"color": "red", "value": 5000}]},
    desc="95th-percentile workflow execution duration.",
))
panels.append(stat(
    "p50 duration",
    f'histogram_quantile(0.50, sum by (le) (rate(traces_span_metrics_duration_milliseconds_bucket{{{WF_W}}}[$__rate_interval])))',
    15, 1, 4, 4, unit="ms", decimals=0,
    desc="Median workflow execution duration.",
))
panels.append(stat(
    "Workflows seen",
    f'count(count by (n8n_workflow_name) (traces_span_metrics_calls_total{{{WF}}}))',
    19, 1, 5, 4, unit="short",
    desc="Distinct workflow names that have emitted workflow.execute spans in range.",
))

# ── Row 2: rate + latency trends ──────────────────────────────────────────
panels.append(row("Rate & latency trends", 5))
panels.append(timeseries(
    "Execution rate by status",
    [target(f'sum by (status_code) (rate(traces_span_metrics_calls_total{{{WF_W}}}[$__rate_interval]))',
            legend="{{status_code}}")],
    0, 6, 12, 8, unit="reqps", stack=True,
    desc="workflow.execute spans/sec split by span status_code.",
    overrides=[
        {"matcher": {"id": "byName", "options": "STATUS_CODE_ERROR"},
         "properties": [{"id": "color", "value": {"fixedColor": "red", "mode": "fixed"}}]},
        {"matcher": {"id": "byName", "options": "STATUS_CODE_OK"},
         "properties": [{"id": "color", "value": {"fixedColor": "green", "mode": "fixed"}}]},
        {"matcher": {"id": "byName", "options": "STATUS_CODE_UNSET"},
         "properties": [{"id": "color", "value": {"fixedColor": "blue", "mode": "fixed"}}]},
    ],
))
panels.append(timeseries(
    "Duration percentiles",
    [target(f'histogram_quantile(0.50, sum by (le) (rate(traces_span_metrics_duration_milliseconds_bucket{{{WF_W}}}[$__rate_interval])))', legend="p50"),
     target(f'histogram_quantile(0.95, sum by (le) (rate(traces_span_metrics_duration_milliseconds_bucket{{{WF_W}}}[$__rate_interval])))', legend="p95"),
     target(f'histogram_quantile(0.99, sum by (le) (rate(traces_span_metrics_duration_milliseconds_bucket{{{WF_W}}}[$__rate_interval])))', legend="p99")],
    12, 6, 12, 8, unit="ms",
    desc="p50 / p95 / p99 workflow execution duration over time, from the spanmetrics histogram.",
))

# ── Row 3: per-workflow ───────────────────────────────────────────────────
panels.append(row("Per-workflow breakdown", 14))
panels.append(table(
    "Workflows by exec rate & error %",
    [target(f'sum by (n8n_workflow_name) (rate(traces_span_metrics_calls_total{{{WF_W}}}[$__rate_interval]))', legend="", instant=True),
     target(f'100 * sum by (n8n_workflow_name) (rate(traces_span_metrics_calls_total{{{WF_W}, {ERR}}}[$__rate_interval])) '
            f'/ clamp_min(sum by (n8n_workflow_name) (rate(traces_span_metrics_calls_total{{{WF_W}}}[$__rate_interval])), 1e-9)', legend="", instant=True)],
    0, 15, 12, 9,
    desc="Per-workflow execution rate (Value #A, /s) and error rate (Value #B, %). Sorted by rate.",
    transformations=[
        {"id": "merge", "options": {}},
        {"id": "organize", "options": {
            "excludeByName": {"Time": True},
            "renameByName": {"n8n_workflow_name": "Workflow",
                             "Value #A": "Exec/s", "Value #B": "Error %"}}},
    ],
    overrides=[
        {"matcher": {"id": "byName", "options": "Error %"},
         "properties": [{"id": "unit", "value": "percent"},
                        {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}},
                        {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                            {"color": "green", "value": None}, {"color": "yellow", "value": 1},
                            {"color": "orange", "value": 5}, {"color": "red", "value": 10}]}}]},
        {"matcher": {"id": "byName", "options": "Exec/s"},
         "properties": [{"id": "unit", "value": "reqps"}, {"id": "decimals", "value": 3}]},
    ],
    sort_by="Exec/s",
))
panels.append(timeseries(
    "Error rate by workflow",
    [target(f'100 * sum by (n8n_workflow_name) (rate(traces_span_metrics_calls_total{{{WF_W}, {ERR}}}[$__rate_interval])) '
            f'/ clamp_min(sum by (n8n_workflow_name) (rate(traces_span_metrics_calls_total{{{WF_W}}}[$__rate_interval])), 1e-9)',
            legend="{{n8n_workflow_name}}")],
    12, 15, 12, 9, unit="percent",
    desc="Per-workflow error rate over time. Spikes localize which workflow is failing.",
))

# ── Row 4: span-type split ────────────────────────────────────────────────
panels.append(row("Span breakdown", 24))
panels.append(timeseries(
    "Call rate by span type",
    [target('sum by (span_name) (rate(traces_span_metrics_calls_total{service_name=~"$service"}[$__rate_interval]))',
            legend="{{span_name}}")],
    0, 25, 24, 7, unit="reqps", stack=True,
    desc="All span types emitted by n8n (workflow.execute vs node.execute …). Not filtered by $workflow — node spans carry no workflow-name dimension.",
))

templating = [
    {
        "name": "service", "type": "query", "label": "Service",
        "datasource": PROM,
        "definition": "label_values(traces_span_metrics_calls_total, service_name)",
        "query": {"qryType": 1, "query": "label_values(traces_span_metrics_calls_total, service_name)",
                  "refId": "PrometheusVariableQueryEditor-VariableQuery"},
        "refresh": 2, "includeAll": True, "multi": True, "hide": 0, "sort": 1,
        "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
        "options": [], "skipUrlSync": False, "regex": "",
    },
    {
        "name": "workflow", "type": "query", "label": "Workflow",
        "datasource": PROM,
        "definition": 'label_values(traces_span_metrics_calls_total{service_name=~"$service", span_name="workflow.execute"}, n8n_workflow_name)',
        "query": {"qryType": 1, "query": 'label_values(traces_span_metrics_calls_total{service_name=~"$service", span_name="workflow.execute"}, n8n_workflow_name)',
                  "refId": "PrometheusVariableQueryEditor-VariableQuery"},
        "refresh": 2, "includeAll": True, "multi": True, "hide": 0, "sort": 1,
        "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
        "options": [], "skipUrlSync": False, "regex": "",
    },
]

dashboard = {
    "uid": "n8n-traces",
    "title": "n8n traces (RED metrics)",
    "description": "RED metrics (rate / errors / duration) derived from n8n's "
                   "OpenTelemetry spans by the Jaeger spanmetrics connector and scraped "
                   "into Prometheus. Reads the prometheus datasource. Empty until n8n "
                   "tracing is enabled (n8n_otel_enabled = true in the n8n workspace). "
                   "For individual trace search, use Explore → Jaeger.",
    "tags": ["n8n", "traces", "otel", "prometheus"],
    "timezone": "browser", "schemaVersion": 42, "version": 1,
    # Live/demo view: short window + fast refresh so fired traffic shows up
    # quickly and the cold-start spike ages out. Widen per-session as needed.
    "refresh": "10s", "time": {"from": "now-30m", "to": "now"},
    # Cross-dashboard nav: dropdown of every dashboard tagged "n8n".
    "links": [{"asDropdown": True, "icon": "external link", "includeVars": False,
               "keepTime": True, "tags": ["n8n"], "targetBlank": False,
               "title": "n8n dashboards", "type": "dashboards"}],
    "timepicker": {}, "templating": {"list": templating},
    "annotations": {"list": []}, "preload": False, "weekStart": "",
    "graphTooltip": 1, "panels": panels,
}

out = "/Users/jan/code/terraform/src/tf-monitoring/dashboards/n8n-traces.json"
with open(out, "w") as f:
    json.dump(dashboard, f, indent=2)
print(f"wrote {out}  ({sum(1 for _ in open(out))} lines, {len(panels)} panels)")
