#!/usr/bin/env python3
"""Import the n8n Monitoring Pack dashboards, adapted to this module.

Upstream: https://github.com/n8n-io/solutions-catalog
          validation/dashboards/dashboards/portable/*.json
Pinned:   commit 9a6253b00638f6ca0549980e74a1426f67c9b9e8

Usage:
    git clone --depth 1 https://github.com/n8n-io/solutions-catalog /tmp/solutions-catalog
    python3 dashboards/import-monitoring-pack.py \
        /tmp/solutions-catalog/validation/dashboards/dashboards/portable

Writes dashboards/n8n-{baseline,business,database,execdata,golden,queue,
saturation}.json. Re-run after bumping the pinned commit and review the diff.

Adaptations (kept deliberately small; see README "Dashboards"):

* Datasource: the pack's `$ds` datasource variable is removed and every
  `${ds}` reference becomes the literal `prometheus` UID. This module
  hardcodes datasource UIDs (dashboards.tf header, AGENTS.md rule 1).
* `$job` / `$ns` default to `n8n`. The n8n ServiceMonitor in
  charts/kube-prometheus-stack.yaml relabels all roles to job="n8n"; the
  variables stay so the dashboards remain portable.
* PgBouncer: nothing in this stack runs PgBouncer, so the three PgBouncer
  panels on "Database & Pooling" are replaced by one text panel saying so
  instead of three panels that are always empty. `$pgjob` is dropped.
* Execution data storage mode: the pack asserts S3 (`s3 must be 1`). tf-n8n
  keeps execution data in PostgreSQL, so the stat shows whichever mode the
  gauge reports as 1 rather than a hardcoded 0.
* Titles use the module's `n8n <Name>` style; UIDs are `n8n-<basename>`.
  Tags, description and a "n8n dashboards" links dropdown match the other
  dashboards in this directory. schemaVersion is bumped to 42 (Grafana 13).

Everything else (queries, layout, thresholds, units) is upstream verbatim.
"""
import copy
import json
import sys
from pathlib import Path

UPSTREAM_COMMIT = "9a6253b00638f6ca0549980e74a1426f67c9b9e8"
UPSTREAM_URL = (
    "https://github.com/n8n-io/solutions-catalog/blob/"
    f"{UPSTREAM_COMMIT}/validation/dashboards/dashboards/portable/"
)

PROM = {"type": "prometheus", "uid": "prometheus"}

# basename -> (local title, extra tags)
DASHBOARDS = {
    "n8n-baseline": ("n8n Baseline", ["prometheus"]),
    "n8n-business": ("n8n Workflows", ["prometheus"]),
    "n8n-database": ("n8n Database & Pooling", ["prometheus", "postgresql"]),
    "n8n-execdata": ("n8n Execution Data", ["prometheus"]),
    "n8n-golden": ("n8n Golden Signals", ["prometheus"]),
    "n8n-queue": ("n8n Queue & Workers", ["prometheus", "redis"]),
    "n8n-saturation": ("n8n Pod & Node Saturation", ["prometheus", "kubernetes"]),
}

LINKS = [
    {
        "asDropdown": True,
        "icon": "external link",
        "includeVars": False,
        "keepTime": True,
        "tags": ["n8n"],
        "targetBlank": False,
        "title": "n8n dashboards",
        "type": "dashboards",
    }
]

PGBOUNCER_TEXT = (
    "### PgBouncer: not deployed\n\n"
    "The upstream pack has three PgBouncer panels here (clients waiting, "
    "max client wait, server active connections). This stack connects n8n "
    "to RDS directly, so there is no PgBouncer and no `pgbouncer_*` or "
    "`cnpg_pgbouncer_*` series. The n8n-side pool panels on this dashboard "
    "(`n8n_db_pool_*`) and `pg_stat_activity_count` cover connection "
    "pressure without it.\n\n"
    "If PgBouncer is added later, restore the panels from the upstream "
    "portable JSON and its `$pgjob` variable."
)


def replace_ds(node):
    """Recursively swap {"uid": "${ds}"} datasource refs for the literal UID."""
    if isinstance(node, dict):
        if node.get("uid") == "${ds}":
            node.clear()
            node.update(PROM)
            return
        for v in node.values():
            replace_ds(v)
    elif isinstance(node, list):
        for v in node:
            replace_ds(v)


def set_current(var, value):
    var["current"] = {"selected": True, "text": value, "value": value}


def adapt_templating(dash):
    keep = []
    for var in dash["templating"]["list"]:
        if var["name"] in ("ds", "pgjob"):
            continue
        if var["name"] in ("job", "ns"):
            set_current(var, "n8n")
        keep.append(var)
    dash["templating"]["list"] = keep


def adapt_database(dash):
    panels = dash["panels"]
    by_id = {p["id"]: p for p in panels}
    waiting, maxwait, active = by_id[36], by_id[37], by_id[38]
    assert waiting["title"].startswith("PgBouncer")
    assert maxwait["title"].startswith("PgBouncer")
    assert active["title"].startswith("PgBouncer")

    text_panel = {
        "id": waiting["id"],
        "type": "text",
        "title": "PgBouncer",
        "gridPos": waiting["gridPos"],
        "options": {"mode": "markdown", "content": PGBOUNCER_TEXT},
    }
    removed_row_y = maxwait["gridPos"]["y"]
    removed_h = maxwait["gridPos"]["h"]

    new_panels = []
    for p in panels:
        if p["id"] == waiting["id"]:
            new_panels.append(text_panel)
            continue
        if p["id"] in (maxwait["id"], active["id"]):
            continue
        if p["gridPos"]["y"] >= removed_row_y:
            p["gridPos"]["y"] -= removed_h
        new_panels.append(p)
    dash["panels"] = new_panels


def adapt_execdata(dash):
    (panel,) = [p for p in dash["panels"] if p["id"] == 56]
    assert panel["title"].startswith("Storage mode active")
    panel["title"] = "Storage mode active"
    panel["description"] = (
        "Which n8n_execution_data_storage_mode gauge is 1. tf-n8n keeps "
        "execution data in PostgreSQL (n8n_execution_data_storage_mode = "
        "database), so expect `db` here. The upstream pack expects `s3`; "
        "the remaining panels apply to either mode."
    )
    panel["targets"][0]["expr"] = (
        'max by (mode) (n8n_execution_data_storage_mode{job="$job"} == 1)'
    )
    panel["targets"][0]["legendFormat"] = "{{mode}}"
    panel["options"]["textMode"] = "name"
    panel["options"]["colorMode"] = "background"


def adapt_baseline(dash):
    (panel,) = [p for p in dash["panels"] if p["id"] == 6]
    assert panel["title"].startswith("Queue backlog")
    panel["title"] = "Queue backlog (n8n view)"
    panel["description"] = (
        "n8n_scaling_mode_queue_jobs_* as reported by the main pods "
        "(N8N_METRICS_INCLUDE_QUEUE_METRICS). Every main reads the same "
        "shared Bull queue, hence max(). Upstream flags this as unreliable "
        "in multi-main; cross-check against the Redis exporter view on the "
        "Queue & Workers dashboard."
    )


SPECIAL = {
    "n8n-database": adapt_database,
    "n8n-execdata": adapt_execdata,
    "n8n-baseline": adapt_baseline,
}


def adapt(basename, upstream):
    dash = copy.deepcopy(upstream)
    title, extra_tags = DASHBOARDS[basename]

    replace_ds(dash)
    adapt_templating(dash)
    SPECIAL.get(basename, lambda d: None)(dash)

    dash["id"] = None
    dash["uid"] = basename
    dash["title"] = title
    dash["tags"] = ["n8n", "monitoring-pack", *extra_tags]
    dash["links"] = LINKS
    dash["schemaVersion"] = 42
    dash["version"] = 1
    dash["description"] = (
        f"n8n Monitoring Pack: {upstream['title']}. Imported from "
        f"{UPSTREAM_URL}{basename}.json (commit {UPSTREAM_COMMIT[:7]}) by "
        "dashboards/import-monitoring-pack.py; see that script for the local "
        "adaptations. Upstream note: " + upstream.get("description", "")
    )
    return dash


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1])
    out_dir = Path(__file__).resolve().parent
    for basename in DASHBOARDS:
        upstream = json.loads((src / f"{basename}.json").read_text())
        dash = adapt(basename, upstream)
        out = out_dir / f"{basename}.json"
        out.write_text(json.dumps(dash, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {out.relative_to(out_dir.parent)}")


if __name__ == "__main__":
    main()
