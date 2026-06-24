# Minimal Prometheus install — server + Alertmanager only.
# node-exporter, kube-state-metrics, and pushgateway are disabled
# because kube-sentinel covers the K8s health signals directly.

prometheus-node-exporter:
  enabled: false

kube-state-metrics:
  enabled: false

prometheus-pushgateway:
  enabled: false

server:
  persistentVolume:
    enabled: false
  service:
    type: NodePort

alertmanager:
  enabled: true
  persistentVolume:
    enabled: false
  service:
    type: NodePort

# Static scrape job for kube-sentinel.
# Templated by Terraform — ${namespace} and ${scrape_interval} are substituted at apply time.
extraScrapeConfigs: |
  - job_name: kube-sentinel
    static_configs:
      - targets:
          - kube-sentinel.${namespace}.svc.cluster.local:8080
    scrape_interval: ${scrape_interval}
