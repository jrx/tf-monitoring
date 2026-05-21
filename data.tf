# EKS cluster identity is produced by the `n8n` Terraform Cloud workspace,
# which now provisions the cluster alongside the n8n application.
data "terraform_remote_state" "n8n" {
  backend = "remote"
  config = {
    workspaces = {
      name = "n8n"
    }
    hostname     = "app.terraform.io"
    organization = "jrxhc"
  }
}

data "aws_eks_cluster" "cluster" {
  name = data.terraform_remote_state.n8n.outputs.cluster_name
}
