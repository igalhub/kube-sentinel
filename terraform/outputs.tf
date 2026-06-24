output "grafana_url" {
  description = "Command to get the Grafana URL on minikube (default credentials: admin / admin)"
  value       = "minikube service grafana -n ${var.namespace} --url"
}

output "prometheus_url" {
  description = "Command to get the Prometheus URL on minikube"
  value       = "minikube service prometheus-server -n ${var.namespace} --url"
}

output "kube_sentinel_url" {
  description = "Command to get the kube-sentinel /metrics URL on minikube"
  value       = "minikube service kube-sentinel -n ${var.namespace} --url"
}
