provider "aws" {
  region = var.aws_region
}

# Use exec-based EKS auth so long Helm installs (kube-prometheus-stack can take
# several minutes) do not fail when the 15-minute aws_eks_cluster_auth token
# expires mid-apply. Requires the `aws` CLI in the Terraform run environment;
# Terraform Cloud default agents include it.
provider "kubernetes" {
  host                   = data.aws_eks_cluster.cluster.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.cluster.certificate_authority[0].data)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args = [
      "eks",
      "get-token",
      "--cluster-name", data.aws_eks_cluster.cluster.name,
      "--region", var.aws_region,
    ]
  }
}

provider "helm" {
  kubernetes {
    host                   = data.aws_eks_cluster.cluster.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.cluster.certificate_authority[0].data)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args = [
        "eks",
        "get-token",
        "--cluster-name", data.aws_eks_cluster.cluster.name,
        "--region", var.aws_region,
      ]
    }
  }
}
