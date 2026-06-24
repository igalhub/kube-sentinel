variable "kubeconfig_path" {
  description = "Path to the kubeconfig file"
  type        = string
  default     = "~/.kube/config"
}

variable "namespace" {
  description = "Kubernetes namespace for the monitoring stack"
  type        = string
  default     = "monitoring"
}

variable "kube_sentinel_image_tag" {
  description = "Docker image tag for kube-sentinel (must be built before terraform apply)"
  type        = string
  default     = "latest"
}

variable "kube_sentinel_image_pull_policy" {
  description = "imagePullPolicy for kube-sentinel. IfNotPresent works after eval $(minikube docker-env) && docker build."
  type        = string
  default     = "IfNotPresent"
}

variable "scrape_interval" {
  description = "Prometheus scrape interval for kube-sentinel"
  type        = string
  default     = "30s"
}

variable "grafana_admin_password" {
  description = "Grafana admin password. Override via terraform.tfvars — never commit a real value."
  type        = string
  sensitive   = true
  default     = "admin"
}
