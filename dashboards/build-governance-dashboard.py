#!/usr/bin/env python3
"""Generate the n8n Governance & Quota dashboard as deterministic JSON.

Prometheus only. Follows the n8n Monitoring Pack conventions (same panel
style, $job variable, no SQL against n8n's tables) so it can be offered
upstream as an eighth pack dashboard.

    python3 dashboards/build-governance-dashboard.py             # local build
    python3 dashboards/build-governance-dashboard.py --portable  # upstream build

Local build  -> dashboards/n8n-governance.json
    Hardcoded `prometheus` datasource UID (module convention), uid
    n8n-governance, schemaVersion 42.
Portable build -> dashboards/upstream/n8n-governance.json
    `$ds` datasource variable, uid n8n-governance-portable, schemaVersion 39,
    title in the pack's "n8n — <Name>" style. Not picked up by dashboards.tf
    (fileset is non-recursive).

Metric prerequisites (n8n 2.39.6 env names):
    N8N_METRICS_INCLUDE_WORKFLOW_STATISTICS      n8n_production_executions, n8n_workflows, ...
    N8N_METRICS_INCLUDE_WORKFLOW_INFO            n8n_active_workflow_info{workflow_id,workflow_name}
    N8N_METRICS_INCLUDE_MESSAGE_EVENT_BUS_METRICS n8n_workflow_{started,success,failed}_total,
                                                  n8n_audit_workflow_updated_total
    N8N_METRICS_INCLUDE_WORKFLOW_ID_LABEL + _NAME_LABEL   labels on the counters above
    (execution duration histogram is on by default)

Semantics worth knowing:
  * Event-bus counters and the duration histogram are emitted by the main
    that owns the execution only (hookFunctionsWorkflowEvents is registered
    in getLifecycleHooksForScalingMain, not on workers), so sum() over
    job="$job" does not double count.
  * "In range" panels use increase() over $__range. They are only as
    complete as Prometheus retention; the 7d / 30d windows on the stale and
    zombie tables need at least that much retention.
  * The lifetime gauges (n8n_production_executions etc.) come from the
    license-metrics repository and survive pod restarts; use them for quota
    against a licence, and the in-range counters for "this month" style
    questions.
  * "Not edited" is derived from n8n_audit_workflow_updated_total, the
    event-bus counter for n8n.audit.workflow.updated. It fires whether or
    not a log-streaming destination exists.

Not carried over from the SQL version: executions by project. n8n exposes no
project label on any metric.
"""
import json
import sys
from pathlib import Path

PORTABLE = "--portable" in sys.argv

DS = {"type": "prometheus", "uid": "${ds}" if PORTABLE else "prometheus"}
JOB = 'job="$job"'

NEXT_ID = 0
def nid():
    global NEXT_ID
    NEXT_ID += 1
    return NEXT_ID


def grid(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def thresholds(*steps):
    """steps: (color, value) pairs; first value is None (base)."""
    if not steps:
        steps = (("green", None),)
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in steps]}


def target(expr, ref="A", *, legend=None, instant=False, interval=None, fmt=None):
    t = {"datasource": DS, "expr": expr, "refId": ref}
    if legend:
        t["legendFormat"] = legend
    if instant:
        t["instant"] = True
        t["range"] = False
    if interval:
        t["interval"] = interval
    if fmt:
        t["format"] = fmt
    return t


def stat(title, targets, x, y, w, h, *, unit="short", desc="", thr=None,
         text_mode="auto", color_mode="value", decimals=None):
    defaults = {"custom": {}, "thresholds": thr or thresholds(), "unit": unit}
    if decimals is not None:
        defaults["decimals"] = decimals
    return {
        "id": nid(), "type": "stat", "title": title, "description": desc,
        "datasource": DS, "gridPos": grid(x, y, w, h),
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": text_mode, "colorMode": color_mode,
        },
        "targets": targets,
    }


def gauge(title, targets, x, y, w, h, *, unit="percent", desc="", thr=None,
          vmin=0, vmax=100):
    return {
        "id": nid(), "type": "gauge", "title": title, "description": desc,
        "datasource": DS, "gridPos": grid(x, y, w, h),
        "fieldConfig": {"defaults": {"custom": {}, "thresholds": thr or thresholds(),
                                     "unit": unit, "min": vmin, "max": vmax},
                        "overrides": []},
        "options": {
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "showThresholdLabels": False, "showThresholdMarkers": True,
        },
        "targets": targets,
    }


def timeseries(title, targets, x, y, w, h, *, unit="short", desc="",
               stacking=None, overrides=None):
    custom = {"drawStyle": "line", "fillOpacity": 8, "lineWidth": 1, "showPoints": "never"}
    if stacking:
        custom["stacking"] = {"mode": stacking, "group": "A"}
        custom["drawStyle"] = "bars"
        custom["fillOpacity"] = 80
    return {
        "id": nid(), "type": "timeseries", "title": title, "description": desc,
        "datasource": DS, "gridPos": grid(x, y, w, h),
        "fieldConfig": {"defaults": {"custom": custom, "thresholds": thresholds(),
                                     "unit": unit},
                        "overrides": overrides or []},
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
        "targets": targets,
    }


def table(title, targets, x, y, w, h, *, desc="", columns, sort_by, overrides=None):
    """Instant multi-query table. `columns` maps raw field name -> header.
    Fields not in `columns` are hidden. Queries are joined on their shared
    labels via the merge transformation."""
    return {
        "id": nid(), "type": "table", "title": title, "description": desc,
        "datasource": DS, "gridPos": grid(x, y, w, h),
        "fieldConfig": {
            "defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"},
                                    "filterable": True},
                         "thresholds": thresholds(), "unit": "short"},
            "overrides": overrides or [],
        },
        "options": {"cellHeight": "sm", "showHeader": True,
                    "sortBy": [{"displayName": sort_by, "desc": True}]},
        "transformations": [
            {"id": "merge", "options": {}},
            {"id": "organize", "options": {
                "excludeByName": {"Time": True, "__name__": True, "job": True},
                "renameByName": columns,
                "indexByName": {name: i for i, name in enumerate(columns)},
            }},
        ],
        "targets": targets,
    }


def pct_override(field, header):
    return {
        "matcher": {"id": "byName", "options": header},
        "properties": [
            {"id": "unit", "value": "percentunit"},
            {"id": "min", "value": 0}, {"id": "max", "value": 1},
            {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}},
            {"id": "color", "value": {"mode": "continuous-RdYlGr"}},
        ],
    }


def heat_override(header, scheme="continuous-BlPu"):
    return {
        "matcher": {"id": "byName", "options": header},
        "properties": [
            {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}},
            {"id": "color", "value": {"mode": scheme}},
        ],
    }


# ---------------------------------------------------------------------------
# PromQL fragments
# ---------------------------------------------------------------------------
BY_WF = "by (workflow_id, workflow_name)"
EXEC_RANGE = f'sum(increase(n8n_workflow_execution_duration_seconds_count{{{JOB}}}[$__range]))'
STARTED_RANGE = f'sum {BY_WF} (increase(n8n_workflow_started_total{{{JOB}}}[$__range]))'
SUCCESS_RANGE = f'sum {BY_WF} (increase(n8n_workflow_success_total{{{JOB}}}[$__range]))'
FAILED_RANGE = f'sum {BY_WF} (increase(n8n_workflow_failed_total{{{JOB}}}[$__range]))'
ACTIVE_WF = f'max {BY_WF} (n8n_active_workflow_info{{{JOB}}})'


def seen(metric, window):
    """Set of workflow_id that had at least one `metric` event inside `window`.

    Event-bus counters are created lazily on the first event and never
    zero-initialised, so a counter whose only sample in the window is `1`
    has no increase. Treat "series exists now but did not at the start of
    the window" as an event too. Aggregated by workflow_id only so a
    renamed workflow still joins onto its current name."""
    sel = f'{metric}{{{JOB}}}'
    return (f'(sum by (workflow_id) (increase({sel}[{window}])) > 0) '
            f'or (sum by (workflow_id) ({sel}) '
            f'unless sum by (workflow_id) ({sel} offset {window}))')


SUCCESS_SEEN = seen("n8n_workflow_success_total", "$stale_window")
STARTED_SEEN = seen("n8n_workflow_started_total", "$stale_window")
UPDATED_SEEN = seen("n8n_audit_workflow_updated_total", "$zombie_window")

STALE = f'{ACTIVE_WF} unless on (workflow_id) ({SUCCESS_SEEN})'
ZOMBIE = (f'{ACTIVE_WF} and on (workflow_id) ({STARTED_SEEN}) '
          f'unless on (workflow_id) ({UPDATED_SEEN})')

quota_thr = thresholds(("green", None), ("yellow", 70), ("orange", 90), ("red", 100))

panels = []

# --- Row 1: volume and quota ------------------------------------------------
panels.append(stat(
    "Executions in range",
    [target(EXEC_RANGE, instant=True)],
    0, 0, 6, 8,
    desc="All executions (success + failed, every mode) finished in the selected "
         "time range. increase() over the execution-duration histogram count; "
         "set the range to the billing period you care about.",
))
panels.append(gauge(
    "Quota consumed in range",
    [target(f'{EXEC_RANGE} / $quota', instant=True)],
    6, 0, 6, 8,
    unit="percentunit", vmin=0, vmax=1,
    thr=thresholds(("green", None), ("yellow", 0.7), ("orange", 0.9), ("red", 1)),
    desc="Executions in range as a share of $quota (editable textbox, top left). "
         "Colours at 70 / 90 / 100 %.",
))
panels.append(stat(
    "Production executions (lifetime)",
    [target(f'max(n8n_production_executions{{{JOB}}})', instant=True)],
    12, 0, 6, 8,
    desc="Instance-lifetime production executions as counted by n8n's licence "
         "metrics (the number a licence quota is checked against). Survives "
         "pod restarts, unlike the counters behind the in-range panels. Needs "
         "N8N_METRICS_INCLUDE_WORKFLOW_STATISTICS.",
))
panels.append(stat(
    "Workflows: total / active",
    [target(f'max(n8n_workflows{{{JOB}}})', "A", legend="total", instant=True),
     target(f'max(n8n_active_workflow_count{{{JOB}}})', "B", legend="active", instant=True)],
    18, 0, 6, 8, text_mode="value_and_name",
    desc="n8n_workflows (all, incl. inactive) next to n8n_active_workflow_count.",
))

# --- Row 2: daily volume -----------------------------------------------------
panels.append(timeseries(
    "Daily execution volume by status",
    [target(f'sum by (status) (increase(n8n_workflow_execution_duration_seconds_count{{{JOB}}}[1d]))',
            legend="{{status}}", interval="1d")],
    0, 8, 24, 8, stacking="normal",
    desc="Trailing 24h increase sampled once a day, stacked success / failed. "
         "Close to, but not exactly, calendar-day totals. Set the range to the "
         "current month for a quota burn-down view.",
    overrides=[
        {"matcher": {"id": "byName", "options": "success"},
         "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]},
        {"matcher": {"id": "byName", "options": "failed"},
         "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]},
    ],
))

# --- Row 3: hotspots ---------------------------------------------------------
panels.append(table(
    "Top 10 workflows by executions (range)",
    [target(f'topk(10, {STARTED_RANGE})', "A", instant=True, fmt="table"),
     target(f'(({SUCCESS_RANGE}) / ({STARTED_RANGE})) and on (workflow_id, workflow_name) topk(10, {STARTED_RANGE})',
            "B", instant=True, fmt="table")],
    0, 16, 12, 8,
    desc="n8n_workflow_started_total by workflow over the range, with success "
         "ratio. Needs the workflow_id / workflow_name label flags.",
    columns={"workflow_name": "Workflow", "workflow_id": "ID",
             "Value #A": "Executions", "Value #B": "Success ratio"},
    sort_by="Executions",
    overrides=[heat_override("Executions"), pct_override("Value #B", "Success ratio")],
))
panels.append(table(
    "Top 10 workflows by failures (range)",
    [target(f'topk(10, {FAILED_RANGE} > 0)', "A", instant=True, fmt="table"),
     target(f'(({FAILED_RANGE}) / ({STARTED_RANGE})) and on (workflow_id, workflow_name) topk(10, {FAILED_RANGE} > 0)',
            "B", instant=True, fmt="table")],
    12, 16, 12, 8,
    desc="n8n_workflow_failed_total by workflow over the range, with failure "
         "ratio. Empty when nothing failed.",
    columns={"workflow_name": "Workflow", "workflow_id": "ID",
             "Value #A": "Failures", "Value #B": "Failure ratio"},
    sort_by="Failures",
    overrides=[
        heat_override("Failures", "continuous-YlRd"),
        {"matcher": {"id": "byName", "options": "Failure ratio"},
         "properties": [
             {"id": "unit", "value": "percentunit"},
             {"id": "min", "value": 0}, {"id": "max", "value": 1},
             {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}},
             {"id": "color", "value": {"mode": "continuous-GrYlRd"}},
         ]},
    ],
))

# --- Row 4: unattended workflows --------------------------------------------
panels.append(table(
    "Stale active workflows (no success in $stale_window)",
    [target(STALE, "A", instant=True, fmt="table"),
     target(f'sum by (workflow_id) (increase(n8n_workflow_failed_total{{{JOB}}}[$stale_window])) '
            f'and on (workflow_id) ({STALE})', "B", instant=True, fmt="table")],
    0, 24, 12, 8,
    desc="Active workflows (n8n_active_workflow_info, leader main) with no "
         "observed n8n_workflow_success_total event in $stale_window, and how "
         "often they failed in that window. Either broken or never triggered. "
         "$stale_window must not exceed Prometheus retention or the table "
         "over-reports.",
    columns={"workflow_name": "Workflow", "workflow_id": "ID", "Value #B": "Failures"},
    sort_by="Failures",
    overrides=[heat_override("Failures", "continuous-YlRd")],
))
panels.append(table(
    "Zombie workflows (running, not edited in $zombie_window)",
    [target(ZOMBIE, "A", instant=True, fmt="table"),
     target(f'sum by (workflow_id) (increase(n8n_workflow_started_total{{{JOB}}}[$zombie_window])) '
            f'and on (workflow_id) ({ZOMBIE})', "B", instant=True, fmt="table")],
    12, 24, 12, 8,
    desc="Active workflows that executed in $stale_window but had no observed "
         "n8n.audit.workflow.updated event in $zombie_window (event-bus counter "
         "n8n_audit_workflow_updated_total). Still doing work, nobody is "
         "looking at them. $zombie_window must not exceed Prometheus retention; "
         "on an instance younger than the window every running workflow "
         "shows here.",
    columns={"workflow_name": "Workflow", "workflow_id": "ID", "Value #B": "Executions"},
    sort_by="Executions",
    overrides=[heat_override("Executions")],
))

# --- Row 5: instance totals --------------------------------------------------
panels.append(stat(
    "Instance totals",
    [target(f'max(n8n_users{{{JOB}}})', "A", legend="users", instant=True),
     target(f'max(n8n_enabled_users{{{JOB}}})', "B", legend="enabled users", instant=True),
     target(f'max(n8n_credentials{{{JOB}}})', "C", legend="credentials", instant=True),
     target(f'max(n8n_manual_executions{{{JOB}}})', "D", legend="manual executions (lifetime)", instant=True)],
    0, 32, 24, 6, text_mode="value_and_name",
    desc="Lifetime counts from n8n's licence metrics. Needs "
         "N8N_METRICS_INCLUDE_WORKFLOW_STATISTICS.",
))

# ---------------------------------------------------------------------------
# Templating
# ---------------------------------------------------------------------------
templating = []
if PORTABLE:
    templating.append({
        "type": "datasource", "name": "ds", "label": "Prometheus",
        "query": "prometheus", "hide": 0, "refresh": 1, "regex": "",
        "multi": False, "includeAll": False, "current": {}, "options": [],
    })
templating.append({
    "type": "query", "name": "job", "label": "n8n scrape job", "hide": 0,
    "datasource": DS,
    "query": {"qryType": 1, "query": "label_values(n8n_nodejs_heap_size_used_bytes, job)",
              "refId": "variable"},
    "definition": "label_values(n8n_nodejs_heap_size_used_bytes, job)",
    "refresh": 1, "sort": 1, "includeAll": False, "multi": False,
    "current": {} if PORTABLE else {"selected": True, "text": "n8n", "value": "n8n"},
    "options": [],
})
templating.append({
    "type": "textbox", "name": "quota", "label": "Execution quota",
    "description": "Executions allowed in the selected range; colours the quota gauge. "
                   "Editable per session.",
    "query": "600000", "hide": 0,
    "current": {"selected": True, "text": "600000", "value": "600000"},
    "options": [{"selected": True, "text": "600000", "value": "600000"}],
})
templating.append({
    "type": "textbox", "name": "stale_window", "label": "Stale window",
    "description": "Lookback for the stale table and the executed-recently test of the zombie table. Keep at or below Prometheus retention.",
    "query": "7d", "hide": 0,
    "current": {"selected": True, "text": "7d", "value": "7d"},
    "options": [{"selected": True, "text": "7d", "value": "7d"}],
})
templating.append({
    "type": "textbox", "name": "zombie_window", "label": "Zombie window",
    "description": "Lookback for the not-edited test of the zombie table. Keep at or below Prometheus retention.",
    "query": "30d", "hide": 0,
    "current": {"selected": True, "text": "30d", "value": "30d"},
    "options": [{"selected": True, "text": "30d", "value": "30d"}],
})

dashboard = {
    "id": None,
    "uid": "n8n-governance-portable" if PORTABLE else "n8n-governance",
    "title": "n8n — Governance & Quota" if PORTABLE else "n8n Governance & Quota",
    "description": (
        "Who is using the instance and what is unattended: execution volume "
        "against a quota, per-workflow hotspots, stale and zombie active "
        "workflows, lifetime instance totals. Prometheus only, no SQL against "
        "n8n's tables. Needs N8N_METRICS_INCLUDE_WORKFLOW_STATISTICS, "
        "_WORKFLOW_INFO, _MESSAGE_EVENT_BUS_METRICS and the "
        "_WORKFLOW_ID_LABEL / _WORKFLOW_NAME_LABEL flags; the 7d / 30d tables "
        "need matching Prometheus retention. Generated by "
        "dashboards/build-governance-dashboard.py."
    ),
    "tags": ["n8n", "portable"] if PORTABLE else ["n8n", "governance", "prometheus"],
    "editable": True,
    "graphTooltip": 1,
    "timezone": "browser",
    "schemaVersion": 39 if PORTABLE else 42,
    "version": 1,
    "refresh": "5m",
    "time": {"from": "now-30d", "to": "now"},
    "timepicker": {},
    "templating": {"list": templating},
    "annotations": {"list": []},
    "links": [] if PORTABLE else [{
        "asDropdown": True, "icon": "external link", "includeVars": False,
        "keepTime": True, "tags": ["n8n"], "targetBlank": False,
        "title": "n8n dashboards", "type": "dashboards"}],
    "panels": panels,
}

here = Path(__file__).resolve().parent
out = (here / "upstream" if PORTABLE else here) / "n8n-governance.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n")
print(f"wrote {out.relative_to(here.parent)}  ({len(panels)} panels)")
