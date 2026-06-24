adminPassword: "${grafana_admin_password}"

persistence:
  enabled: false

service:
  type: NodePort

# Pre-provision the Prometheus datasource so the dashboard works immediately.
datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
      - name: Prometheus
        type: prometheus
        url: http://prometheus-server.${namespace}.svc.cluster.local
        isDefault: true
        access: proxy

# Sidecar watches for ConfigMaps labelled grafana_dashboard=1 and
# auto-provisions them as dashboards. The kube-sentinel dashboard ConfigMap
# is created by Terraform before this release, so it appears on first load.
sidecar:
  dashboards:
    enabled: true
    label: grafana_dashboard
    labelValue: "1"
