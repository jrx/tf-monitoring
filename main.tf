terraform {
  backend "remote" {}

  required_providers {
    kubectl = {
      source  = "gavinbunney/kubectl"
      version = ">= 1.7.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "terraform_remote_state" "eks" {
  backend = "remote"
  config = {
    workspaces = {
      name = "eks-dev"
    }
    hostname     = "app.terraform.io"
    organization = "jrx"
  }
}

data "aws_eks_cluster" "cluster" {
  name = data.terraform_remote_state.eks.outputs.cluster_id
}
data "aws_eks_cluster_auth" "eks_cluster" {
  name = data.aws_eks_cluster.cluster.name
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.cluster.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.cluster.certificate_authority.0.data)
  token                  = data.aws_eks_cluster_auth.eks_cluster.token
}

provider "helm" {
  kubernetes {
    host                   = data.aws_eks_cluster.cluster.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.cluster.certificate_authority.0.data)
    token                  = data.aws_eks_cluster_auth.eks_cluster.token
  }
}

resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = var.monitoring-namespace
  }
}

# Prometheus Operator and Grafana

provider "kubectl" {
  host                   = data.aws_eks_cluster.cluster.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.cluster.certificate_authority.0.data)
  token                  = data.aws_eks_cluster_auth.eks_cluster.token
  load_config_file       = false
}

data "kubectl_path_documents" "monitoring-setup" {
  pattern = "./manifests/setup/*.yaml"
}

data "kubectl_path_documents" "monitoring" {
  pattern = "./manifests/*.yaml"
}

resource "kubectl_manifest" "monitoring-setup" {
  for_each          = toset(data.kubectl_path_documents.monitoring-setup.documents)
  yaml_body         = each.value
  server_side_apply = true
  wait              = true
  depends_on = [
    kubernetes_namespace.monitoring,
  ]
}

resource "kubectl_manifest" "monitoring" {
  for_each          = data.kubectl_path_documents.monitoring.manifests
  yaml_body         = each.value
  server_side_apply = true
  wait              = false
  wait_for_rollout  = false
  validate_schema   = false
  depends_on = [
    kubernetes_namespace.monitoring,
    kubectl_manifest.monitoring-setup,
  ]
}

# promtail

resource "helm_release" "loki" {
  name       = "loki"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "loki"
  namespace  = kubernetes_namespace.monitoring.id

  values = [
    file("${path.module}/charts/loki.yaml")
  ]

  depends_on = [
    kubernetes_namespace.monitoring,
    kubectl_manifest.monitoring-setup,
  ]
}

# Promtail

resource "helm_release" "promtail" {
  name       = "promtail"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "promtail"
  namespace  = kubernetes_namespace.monitoring.id

  values = [
    file("${path.module}/charts/promtail.yaml")
  ]

  depends_on = [
    kubernetes_namespace.monitoring,
    kubectl_manifest.monitoring-setup,
  ]
}