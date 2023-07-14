terraform {
  backend "remote" {}
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

resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = var.monitoring-namespace
  }
}


# ln -s /Users/jrepnak/test/kubernetes/src/kube-prometheus/manifests /manifests
data "kubectl_path_documents" "monitoring-setup" {
    pattern = "./manifests/setup/*.yaml"
}


# kubectl apply --server-side -f manifests/setup
# kubectl wait \
# 	--for condition=Established \
# 	--all CustomResourceDefinition \
# 	--namespace=monitoring
# kubectl apply -f manifests/