#!/usr/bin/env python3
"""Generate the n8n audit-events Grafana dashboard as deterministic JSON.

    python3 dashboards/build-audit-dashboard.py             # local build
    python3 dashboards/build-audit-dashboard.py --portable  # upstream build

Local build  -> dashboards/n8n-audit-events.json
    Hardcoded `loki` datasource UID and the `{source="n8n-log-streaming"}`
    stream selector this module's Alloy pipeline sets. Picked up by
    dashboards.tf on terraform apply.
Portable build -> dashboards/upstream/n8n-audit-events.json
    `$loki` datasource variable and a `$stream` textbox holding the stream
    selector, uid n8n-audit-events-portable, schemaVersion 39, title in the
    n8n Monitoring Pack's "n8n — <Name>" style. Not picked up by
    dashboards.tf (fileset is non-recursive).

Data contract: n8n Enterprise Log Streaming, syslog destination, received by
Grafana Alloy (loki.source.syslog, RFC 5424) and shipped to Loki with the
JSON event as the log line. Every panel does `| json`, so the fields are
n8n's own event schema (eventName, payload_userId, payload__email,
payload_workflowName, ...). The `severity` / `facility` labels are derived
from the syslog PRI byte by the receiver; a receiver that does not set them
leaves the "Severity & facility" row empty and nothing else breaks.
"""
import json
import sys
from pathlib import Path

PORTABLE = "--portable" in sys.argv

LOKI = {"type": "loki", "uid": "${loki}" if PORTABLE else "loki"}
# Stream selector. Local: literal label the Alloy pipeline sets. Portable:
# textbox variable so a different receiver can point the dashboard at its
# own stream without editing 27 queries.
SEL = "{${stream:raw}}" if PORTABLE else '{source="n8n-log-streaming"}'

NEXT_ID = 0
def nid():
    global NEXT_ID
    NEXT_ID += 1
    return NEXT_ID


def grid(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def row(title, y):
    return {
        "id": nid(),
        "type": "row",
        "title": title,
        "collapsed": False,
        "gridPos": grid(0, y, 24, 1),
        "panels": [],
    }


def stat(title, expr, x, y, w=6, h=4, *, unit="short", thresholds=None, description=""):
    if thresholds is None:
        thresholds = {
            "mode": "absolute",
            "steps": [{"color": "blue", "value": None}],
        }
    return {
        "id": nid(),
        "type": "stat",
        "title": title,
        "description": description,
        "datasource": LOKI,
        "gridPos": grid(x, y, w, h),
        "targets": [{
            "datasource": LOKI,
            "expr": expr,
            "queryType": "instant",
            "refId": "A",
        }],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "thresholds": thresholds,
                "color": {"mode": "thresholds"},
                "mappings": [],
            },
            "overrides": [],
        },
        "options": {
            "orientation": "auto",
            "reduceOptions": {
                "calcs": ["lastNotNull"],
                "fields": "",
                "values": False,
            },
            "colorMode": "value",
            "graphMode": "none",
            "textMode": "auto",
        },
    }


def timeseries(title, expr, x, y, w, h, *, legend_format=None,
               description="", unit="short"):
    target = {
        "datasource": LOKI,
        "expr": expr,
        "refId": "A",
    }
    if legend_format:
        target["legendFormat"] = legend_format
    return {
        "id": nid(),
        "type": "timeseries",
        "title": title,
        "description": description,
        "datasource": LOKI,
        "gridPos": grid(x, y, w, h),
        "targets": [target],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "custom": {
                    "drawStyle": "bars",
                    "lineWidth": 1,
                    "fillOpacity": 80,
                    "stacking": {"mode": "normal", "group": "A"},
                    "showPoints": "never",
                },
                "thresholds": {
                    "mode": "absolute",
                    "steps": [{"color": "green", "value": None}],
                },
            },
            "overrides": [],
        },
        "options": {
            "legend": {
                "displayMode": "list",
                "placement": "bottom",
                "showLegend": True,
            },
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }


def table(title, expr, x, y, w, h, *, description="",
          rename=None, sort_by=None, value_unit="short"):
    transformations = []
    if rename:
        # Rename auto-extracted column names ("Value", "payload_workflowName", ...)
        transformations.append({
            "id": "organize",
            "options": {
                "excludeByName": {"Time": True},
                "renameByName": rename,
                "indexByName": {},
            },
        })
    if sort_by:
        transformations.append({
            "id": "sortBy",
            "options": {
                "fields": {},
                "sort": [{"field": sort_by, "desc": True}],
            },
        })
    panel = {
        "id": nid(),
        "type": "table",
        "title": title,
        "description": description,
        "datasource": LOKI,
        "gridPos": grid(x, y, w, h),
        "targets": [{
            "datasource": LOKI,
            "expr": expr,
            "queryType": "instant",
            "format": "table",
            "refId": "A",
        }],
        "fieldConfig": {
            "defaults": {
                "unit": value_unit,
                "custom": {
                    "align": "left",
                    "cellOptions": {"type": "auto"},
                    "filterable": True,
                    "inspect": False,
                },
                "thresholds": {
                    "mode": "absolute",
                    "steps": [{"color": "green", "value": None}],
                },
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Value #A"},
                    "properties": [
                        {"id": "custom.cellOptions",
                         "value": {"mode": "gradient", "type": "color-background"}},
                        {"id": "color",
                         "value": {"mode": "continuous-BlPu"}},
                    ],
                },
            ],
        },
        "options": {
            "cellHeight": "sm",
            "showHeader": True,
            "sortBy": [{"displayName": sort_by, "desc": True}] if sort_by else [],
        },
        "transformations": transformations,
    }
    return panel


def logs_panel(title, expr, x, y, w, h, *, description=""):
    return {
        "id": nid(),
        "type": "logs",
        "title": title,
        "description": description,
        "datasource": LOKI,
        "gridPos": grid(x, y, w, h),
        "targets": [{
            "datasource": LOKI,
            "expr": expr,
            "refId": "A",
            "queryType": "range",
        }],
        "options": {
            "showTime": True,
            "showLabels": False,
            "showCommonLabels": False,
            "wrapLogMessage": True,
            "prettifyLogMessage": False,
            "enableLogDetails": True,
            "dedupStrategy": "none",
            "sortOrder": "Descending",
        },
    }


# Common LogQL fragments
AUDIT_FILTER  = f'{SEL} | json | eventName=~`n8n\\.audit\\..*`'
USER_FILTER   = f'{SEL} | json | eventName=~`n8n\\.audit\\.user\\..*`'
WF_FILTER     = f'{SEL} | json | eventName=~`n8n\\.audit\\.workflow\\..*`'
CRED_FILTER   = f'{SEL} | json | eventName=~`n8n\\.audit\\.user\\.(credentials|api|mfa)\\..*`'
VARPKG_FILTER = f'{SEL} | json | eventName=~`n8n\\.audit\\.(variable|package)\\..*`'
EXEC_FILTER   = f'{SEL} | json | eventName=~`n8n\\.audit\\.execution\\..*`'


panels = []

# === Summary row ===
panels.append(row("Audit summary", 0))
panels.append(stat(
    "Total audit events",
    f"sum(count_over_time({AUDIT_FILTER} [$__range]))",
    x=0, y=1, w=6, h=4,
    description="All n8n.audit.* events received in the selected time range.",
))
panels.append(stat(
    "Distinct event types",
    f"count(sum by (eventName) (count_over_time({AUDIT_FILTER} [$__range])))",
    x=6, y=1, w=6, h=4,
    description="Unique eventName values seen, e.g. n8n.audit.workflow.created.",
))
panels.append(stat(
    "Distinct users",
    f'count(sum by (payload_userId) (count_over_time({USER_FILTER} | payload_userId != `` [$__range])))',
    x=12, y=1, w=6, h=4,
    description="Unique userIds appearing in any n8n.audit.user.* event.",
))
panels.append(stat(
    "Failed login + email events",
    f'sum(count_over_time({SEL} | json '
    '| eventName=~`n8n\\.audit\\.user\\.(login|email)\\.failed` [$__range]))',
    x=18, y=1, w=6, h=4,
    description="Auth and email-send failures. Spikes warrant investigation.",
    thresholds={
        "mode": "absolute",
        "steps": [
            {"color": "green", "value": None},
            {"color": "yellow", "value": 1},
            {"color": "red", "value": 5},
        ],
    },
))

# === Severity & facility ===
# These are real Loki labels promoted from the syslog PRI field by Alloy
# (see charts/alloy-config.river). Use them to filter any other panel by
# adding `severity="warning"` or similar.
panels.append(row("Severity & facility", 5))
panels.append(timeseries(
    "Events by severity",
    f'sum by (severity) (count_over_time({SEL} [$__interval]))',
    x=0, y=6, w=12, h=7,
    legend_format="{{severity}}",
    description="All log-streaming events split by syslog severity. Derived from the syslog PRI field, not the message body.",
))
panels.append(table(
    "Counts by severity & facility",
    f'sum by (severity, facility) (count_over_time({SEL} [$__range]))',
    x=12, y=6, w=12, h=7,
    description="Cross-tab of severity × facility. Useful to spot misconfigured producers or warning/error spikes.",
    rename={"severity": "Severity", "facility": "Facility", "Value": "Count"},
    sort_by="Count",
))

# === Activity over time ===
panels.append(row("Activity over time", 13))
panels.append(timeseries(
    "Audit events by name",
    f"sum by (eventName) (count_over_time({AUDIT_FILTER} [$__interval]))",
    x=0, y=14, w=24, h=8,
    legend_format="{{eventName}}",
    description="Every audit event, broken down by full eventName. Stacked.",
))

# === User audit ===
panels.append(row("Identity & access", 22))
panels.append(timeseries(
    "Auth & user lifecycle",
    f'sum by (eventName) (count_over_time({SEL} | json '
    '| eventName=~`n8n\\.audit\\.user\\.(login|signedup|invited|deleted|reset)\\..*` [$__interval]))',
    x=0, y=23, w=12, h=8,
    legend_format="{{eventName}}",
    description="login.success / login.failed / signedup / invited / deleted / reset.requested / reset.",
))
panels.append(table(
    "Most active users (audit events)",
    'topk(10, sum by (payload__email, payload_userId) '
    f'(count_over_time({USER_FILTER} | payload__email != `` [$__range])))',
    x=12, y=23, w=12, h=8,
    description="Top 10 users by audit-event count in the selected range.",
    rename={
        "payload__email": "Email",
        "payload_userId": "User ID",
        "Value": "Events",
    },
    sort_by="Events",
))

# === Audit activity by user ===
# Cross-tabulates audit events by actor (payload._email -> payload__email).
# Filters payload__email != "" so only attributed events show; the rare
# events without an email are surfaced via the "Recent audit events" log
# panel which falls back to user:UUID or "(no user)".
panels.append(row("Audit activity by user", 31))
panels.append(table(
    "Top users by audit activity",
    'topk(20, sum by (payload__email, eventName) '
    f'(count_over_time({AUDIT_FILTER} | payload__email != `` [$__range])))',
    x=0, y=32, w=12, h=8,
    description="Top 20 (user, event-name) pairs across all n8n.audit.* events. Click a column header to re-sort.",
    rename={
        "payload__email": "User",
        "eventName": "Event",
        "Value": "Count",
    },
    sort_by="Count",
))
panels.append(table(
    "Top users by credential / API / MFA action",
    'topk(20, sum by (payload__email, eventName) '
    f'(count_over_time({CRED_FILTER} | payload__email != `` [$__range])))',
    x=12, y=32, w=12, h=8,
    description="Same cross-tab restricted to credentials, API keys, and MFA events. Security-sensitive subset.",
    rename={
        "payload__email": "User",
        "eventName": "Event",
        "Value": "Count",
    },
    sort_by="Count",
))

# === Workflow audit ===
panels.append(row("Workflow audit", 40))
panels.append(timeseries(
    "Workflow lifecycle",
    f"sum by (eventName) (count_over_time({WF_FILTER} [$__interval]))",
    x=0, y=41, w=12, h=8,
    legend_format="{{eventName}}",
    description="created / updated / deleted / activated / deactivated / archived / executed.",
))
panels.append(table(
    "Most-touched workflows",
    'topk(15, sum by (payload__email, payload_workflowName, eventName) '
    f'(count_over_time({WF_FILTER} | payload_workflowName != `` [$__range])))',
    x=12, y=41, w=12, h=8,
    description="Workflows with the most audit activity, attributed to the user who triggered each event.",
    rename={
        "payload__email": "User",
        "payload_workflowName": "Workflow",
        "eventName": "Event",
        "Value": "Count",
    },
    sort_by="Count",
))

# === Security ===
panels.append(row("Credentials, API keys, MFA", 49))
panels.append(timeseries(
    "Credential, API key & MFA events",
    f"sum by (eventName) (count_over_time({CRED_FILTER} [$__interval]))",
    x=0, y=50, w=12, h=8,
    legend_format="{{eventName}}",
    description="credentials.created / shared / updated / deleted, api.created / deleted, mfa.enabled / disabled. For per-user breakdown see 'Top users by credential / API / MFA action' above.",
))
panels.append(timeseries(
    "Variables & community packages",
    f"sum by (eventName) (count_over_time({VARPKG_FILTER} [$__interval]))",
    x=12, y=50, w=12, h=8,
    legend_format="{{eventName}}",
    description="variable.created / updated / deleted, package.installed / updated / deleted.",
))

# === Execution data reveals ===
panels.append(row("Execution data access", 58))
panels.append(timeseries(
    "Execution data reveals",
    f"sum by (eventName) (count_over_time({EXEC_FILTER} [$__interval]))",
    x=0, y=59, w=12, h=8,
    legend_format="{{eventName}}",
    description="When users reveal sensitive execution data in the editor.",
))
panels.append(table(
    "Recent execution-data reveals",
    'topk(20, sum by (payload__email, payload_userId, payload_executionId) '
    f'(count_over_time({EXEC_FILTER} | payload_executionId != `` [$__range])))',
    x=12, y=59, w=12, h=8,
    description="Who revealed which execution payload in the selected range.",
    rename={
        "payload__email": "Email",
        "payload_userId": "User ID",
        "payload_executionId": "Execution ID",
        "Value": "Reveals",
    },
    sort_by="Reveals",
))

# === Raw events ===
panels.append(row("Raw audit stream", 67))
panels.append(logs_panel(
    "Recent audit events",
    f'{SEL} | json '
    '| eventName=~`n8n\\.audit\\..*` '
    # Actor first, then severity + eventName, then context fields.
    # Falls back from email -> user:UUID -> "(no user)" so every line is
    # attributable even for service-account-style events.
    '| line_format "{{if .payload__email}}{{.payload__email}}'
    '{{else if .payload_userId}}user:{{.payload_userId}}'
    '{{else}}(no user){{end}}  [{{.severity}}] {{.eventName}}'
    '{{if .payload_workflowName}}  workflow=\\"{{.payload_workflowName}}\\"{{end}}'
    '{{if .payload_credentialName}}  credential=\\"{{.payload_credentialName}}\\"{{end}}'
    '{{if .payload_executionId}}  exec={{.payload_executionId}}{{end}}'
    '{{if .payload_instanceType}}  instance={{.payload_instanceType}}/{{.payload_instanceRole}}{{end}}"',
    x=0, y=68, w=24, h=12,
    description="Live tail of all n8n.audit.* events. Each line begins with the actor (email, user:UUID fallback, or '(no user)'), then severity and event name, then any contextual identifiers (workflow / credential / execution / instance role).",
))


templating = []
if PORTABLE:
    templating.append({
        "type": "datasource", "name": "loki", "label": "Loki",
        "query": "loki", "hide": 0, "refresh": 1, "regex": "",
        "multi": False, "includeAll": False, "current": {}, "options": [],
    })
    templating.append({
        "type": "textbox", "name": "stream", "label": "Stream selector",
        "description": "Loki label matcher(s) identifying the n8n log-streaming "
                       "stream, without the braces.",
        "query": 'source="n8n-log-streaming"', "hide": 0,
        "current": {"selected": True, "text": 'source="n8n-log-streaming"',
                    "value": 'source="n8n-log-streaming"'},
        "options": [{"selected": True, "text": 'source="n8n-log-streaming"',
                     "value": 'source="n8n-log-streaming"'}],
    })

dashboard = {
    "id": None,
    "uid": "n8n-audit-events-portable" if PORTABLE else "n8n-audit-events",
    "title": "n8n — Audit Events" if PORTABLE else "n8n Audit Events",
    "description": (
        "Who did what: n8n Enterprise Log Streaming audit events (n8n.audit.*) "
        "read from Loki. Identity and access, per-user attribution, workflow "
        "lifecycle, credential / API key / MFA changes, execution-data reveals, "
        "raw event stream. Needs a licence with Log Streaming, a syslog "
        "destination pointed at a Loki-shipping receiver, and the JSON event as "
        "the log line. Generated by dashboards/build-audit-dashboard.py."
    ),
    "tags": ["n8n", "portable"] if PORTABLE else ["n8n", "audit", "loki", "log-streaming"],
    "editable": True,
    "graphTooltip": 1,
    "timezone": "browser",
    "schemaVersion": 39 if PORTABLE else 42,
    "version": 1,
    "refresh": "30s",
    "time": {"from": "now-6h", "to": "now"},
    "timepicker": {},
    "templating": {"list": templating},
    "annotations": {"list": []},
    # Cross-dashboard nav: dropdown of every dashboard tagged "n8n".
    "links": [] if PORTABLE else [{
        "asDropdown": True, "icon": "external link", "includeVars": False,
        "keepTime": True, "tags": ["n8n"], "targetBlank": False,
        "title": "n8n dashboards", "type": "dashboards"}],
    "panels": panels,
}

here = Path(__file__).resolve().parent
out = (here / "upstream" if PORTABLE else here) / "n8n-audit-events.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n")
print(f"wrote {out.relative_to(here.parent)}  ({len(panels)} panels)")
