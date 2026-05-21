# Wiring for the "n8n-postgres" Grafana datasource consumed by the
# n8n-workflow-execution-analytics dashboard.
#
# SECURITY NOTE: this datasource currently re-uses n8n's application DB
# user (n8n's full read/write owner on the n8n schema). That means
# anyone with Grafana edit permissions can run DELETE/DROP through the
# Explore tab. Acceptable for a sandbox cluster, not for production.
# When this leaves sandbox, replace with a dedicated read-only role
# (see ./README.md "n8n PostgreSQL datasource" section).
#
# The DB host comes from the n8n Terraform Cloud workspace's `rds_endpoint`
# remote-state output — single source of truth for the RDS hostname. The
# remaining DB attributes are not exposed by the n8n workspace, so they
# stay as overridable variables with sensible defaults.

variable "n8n_db_port" {
  description = "TCP port for the n8n Postgres database."
  type        = number
  default     = 5432
}

variable "n8n_db_name" {
  description = "Database name inside the n8n RDS instance."
  type        = string
  default     = "n8n_enterprise"
}

variable "n8n_db_user" {
  description = "Postgres role Grafana authenticates as. Currently n8n's application user (sandbox only)."
  type        = string
  default     = "n8n"
}

# Kubernetes Secrets cannot be referenced across namespaces, so copy
# n8n's DB password (exposed by the n8n workspace via remote state)
# into the monitoring namespace where Grafana runs. The chart values
# project this Secret into the Grafana container as the env var
# N8N_POSTGRES_PASSWORD, referenced from the datasource provisioning
# YAML as `$N8N_POSTGRES_PASSWORD`.
#
# Why an env var and not $__file{...}: Grafana's `$__file{}` syntax is
# resolved by the grafana.ini parser, NOT by the datasource provisioning
# YAML parser — in YAML it becomes the literal password string. Env-var
# interpolation (`$X` / `${X}`) IS supported in provisioning YAML, so we
# go that route instead.
resource "kubernetes_secret" "n8n_postgres_grafana" {
  metadata {
    name      = "n8n-postgres-grafana"
    namespace = kubernetes_namespace.monitoring.metadata[0].name
  }
  type = "Opaque"
  data = {
    password = data.terraform_remote_state.n8n.outputs.db_password
  }
}
