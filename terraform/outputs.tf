output "grafana_url" {
  description = "Grafana access — minikube: run 'minikube service grafana -n monitoring --url'; k3s/other: run 'kubectl get svc grafana -n monitoring' and use the NodePort"
  value       = "kubectl get svc grafana -n ${var.namespace}"
}

output "prometheus_url" {
  description = "Prometheus access — minikube: run 'minikube service prometheus-server -n monitoring --url'; k3s/other: run 'kubectl get svc prometheus-server -n monitoring' and use the NodePort"
  value       = "kubectl get svc prometheus-server -n ${var.namespace}"
}

output "kube_sentinel_url" {
  description = "kube-sentinel access — minikube: run 'minikube service kube-sentinel -n monitoring --url'; k3s/other: run 'kubectl get svc kube-sentinel -n monitoring' and use the NodePort"
  value       = "kubectl get svc kube-sentinel -n ${var.namespace}"
}

