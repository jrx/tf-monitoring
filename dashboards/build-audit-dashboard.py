#!/usr/bin/env python3
"""Generate the n8n audit-events Grafana dashboard as deterministic JSON.

Output: dashboards/n8n-audit-events.json under this Terraform module.
The repo's dashboard provisioner picks it up automatically on terraform apply.
"""
import json
import sys

LOKI = {"type": "loki", "uid": "loki"}

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
            "reduceOptions": {
                "calcs": ["lastNotNull"],
                "fields": "",
                "values": False,
            },
            "colorMode": "value",
            "graphMode": "area",
            "textMode": "auto",
            "justifyMode": "auto",
        },
        "transparent": True,
    }


def timeseries(title, expr, x, y, w, h, *, legend_format=None,
               description="", unit="short", calcs=("last", "max", "sum")):
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
                    "drawStyle": "line",
                    "lineInterpolation": "stepAfter",
                    "lineWidth": 1,
                    "fillOpacity": 12,
                    "stacking": {"mode": "normal", "group": "A"},
                    "showPoints": "never",
                    "spanNulls": True,
                    "pointSize": 4,
                    "axisPlacement": "auto",
                },
                "color": {"mode": "palette-classic"},
            },
            "overrides": [],
        },
        "options": {
            "legend": {
                "calcs": list(calcs),
                "displayMode": "table",
                "placement": "right",
                "showLegend": True,
            },
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
        "transparent": True,
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
        "transparent": True,
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
        "transparent": True,
    }


# Common LogQL fragments
AUDIT_FILTER  = '{source="n8n-log-streaming"} | json | eventName=~`n8n\\.audit\\..*`'
USER_FILTER   = '{source="n8n-log-streaming"} | json | eventName=~`n8n\\.audit\\.user\\..*`'
WF_FILTER     = '{source="n8n-log-streaming"} | json | eventName=~`n8n\\.audit\\.workflow\\..*`'
CRED_FILTER   = '{source="n8n-log-streaming"} | json | eventName=~`n8n\\.audit\\.user\\.(credentials|api|mfa)\\..*`'
VARPKG_FILTER = '{source="n8n-log-streaming"} | json | eventName=~`n8n\\.audit\\.(variable|package)\\..*`'
EXEC_FILTER   = '{source="n8n-log-streaming"} | json | eventName=~`n8n\\.audit\\.execution\\..*`'


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
    'sum(count_over_time({source="n8n-log-streaming"} | json '
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
    'sum by (severity) (count_over_time({source="n8n-log-streaming"} [$__interval]))',
    x=0, y=6, w=12, h=7,
    legend_format="{{severity}}",
    description="All log-streaming events split by syslog severity. Derived from the syslog PRI field, not the message body.",
))
panels.append(table(
    "Counts by severity & facility",
    'sum by (severity, facility) (count_over_time({source="n8n-log-streaming"} [$__range]))',
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
    'sum by (eventName) (count_over_time({source="n8n-log-streaming"} | json '
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

# === Workflow audit ===
panels.append(row("Workflow audit", 31))
panels.append(timeseries(
    "Workflow lifecycle",
    f"sum by (eventName) (count_over_time({WF_FILTER} [$__interval]))",
    x=0, y=32, w=12, h=8,
    legend_format="{{eventName}}",
    description="created / updated / deleted / activated / deactivated / archived / executed.",
))
panels.append(table(
    "Most-touched workflows",
    'topk(15, sum by (payload_workflowName, eventName) '
    f'(count_over_time({WF_FILTER} | payload_workflowName != `` [$__range])))',
    x=12, y=32, w=12, h=8,
    description="Workflows with the most audit activity in the selected range.",
    rename={
        "payload_workflowName": "Workflow",
        "eventName": "Event",
        "Value": "Count",
    },
    sort_by="Count",
))

# === Security ===
panels.append(row("Credentials, API keys, MFA", 40))
panels.append(timeseries(
    "Credential, API key & MFA events",
    f"sum by (eventName) (count_over_time({CRED_FILTER} [$__interval]))",
    x=0, y=41, w=12, h=8,
    legend_format="{{eventName}}",
    description="credentials.created / shared / updated / deleted, api.created / deleted, mfa.enabled / disabled.",
))
panels.append(timeseries(
    "Variables & community packages",
    f"sum by (eventName) (count_over_time({VARPKG_FILTER} [$__interval]))",
    x=12, y=41, w=12, h=8,
    legend_format="{{eventName}}",
    description="variable.created / updated / deleted, package.installed / updated / deleted.",
))

# === Execution data reveals ===
panels.append(row("Execution data access", 49))
panels.append(timeseries(
    "Execution data reveals",
    f"sum by (eventName) (count_over_time({EXEC_FILTER} [$__interval]))",
    x=0, y=50, w=12, h=8,
    legend_format="{{eventName}}",
    description="When users reveal sensitive execution data in the editor.",
))
panels.append(table(
    "Recent execution-data reveals",
    'topk(20, sum by (payload__email, payload_userId, payload_executionId) '
    f'(count_over_time({EXEC_FILTER} | payload_executionId != `` [$__range])))',
    x=12, y=50, w=12, h=8,
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
panels.append(row("Raw audit stream", 58))
panels.append(logs_panel(
    "Recent audit events",
    '{source="n8n-log-streaming"} | json '
    '| eventName=~`n8n\\.audit\\..*` '
    '| line_format "[{{.severity}}] {{.eventName}}'
    '{{if .payload__email}}  email={{.payload__email}}{{end}}'
    '{{if .payload_workflowName}}  workflow=\\"{{.payload_workflowName}}\\"{{end}}'
    '{{if .payload_credentialName}}  credential=\\"{{.payload_credentialName}}\\"{{end}}'
    '{{if .payload_executionId}}  exec={{.payload_executionId}}{{end}}'
    '{{if .payload_instanceType}}  instance={{.payload_instanceType}}/{{.payload_instanceRole}}{{end}}"',
    x=0, y=59, w=24, h=12,
    description="Live tail of all n8n.audit.* events with severity badge. Click a line to see the full JSON payload.",
))


dashboard = {
    "uid": "n8n-audit-events",
    "title": "n8n audit events",
    "description": "Enterprise Log Streaming: audit-event view "
                   "sourced from Loki tenant_id=1, label source=\"n8n-log-streaming\".",
    "tags": ["n8n", "audit", "loki", "log-streaming"],
    "timezone": "browser",
    "schemaVersion": 42,
    "version": 1,
    "refresh": "30s",
    "time": {"from": "now-6h", "to": "now"},
    "timepicker": {},
    "templating": {"list": []},
    "annotations": {"list": []},
    "preload": False,
    "weekStart": "",
    "panels": panels,
}

out = "/Users/jan/code/terraform/src/tf-monitoring/dashboards/n8n-audit-events.json"
with open(out, "w") as f:
    json.dump(dashboard, f, indent=2)
print(f"wrote {out}  ({sum(1 for _ in open(out))} lines, {len(panels)} panels)")
