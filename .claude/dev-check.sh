#!/usr/bin/env bash
# Project-specific service health checks for kube-sentinel.
# Each check prints: SERVICE_NAME | STATUS | detail
# STATUS: UP or DOWN

set -uo pipefail

# --- minikube cluster ---
if minikube status >/dev/null 2>&1; then
  echo "minikube | UP | cluster running"
else
  echo "minikube | DOWN | minikube status failed (docker daemon may be down)"
fi

# --- kube-sentinel exporter /metrics ---
EXPORTER_URL=$(minikube service kube-sentinel -n monitoring --url 2>/dev/null | head -n1)
if [ -n "$EXPORTER_URL" ] && curl -sf "${EXPORTER_URL}/metrics" >/dev/null 2>&1; then
  echo "kube-sentinel-exporter | UP | /metrics responding at ${EXPORTER_URL}"
else
  echo "kube-sentinel-exporter | DOWN | no response on /metrics"
fi

# --- Prometheus ---
PROM_URL=$(minikube service prometheus-server -n monitoring --url 2>/dev/null | head -n1)
if [ -n "$PROM_URL" ] && curl -sf "${PROM_URL}/-/healthy" >/dev/null 2>&1; then
  echo "prometheus | UP | healthy at ${PROM_URL}"
else
  echo "prometheus | DOWN | no response on /-/healthy"
fi

# --- Grafana ---
GRAFANA_URL=$(minikube service grafana -n monitoring --url 2>/dev/null | head -n1)
if [ -n "$GRAFANA_URL" ] && curl -sf "${GRAFANA_URL}/api/health" >/dev/null 2>&1; then
  echo "grafana | UP | healthy at ${GRAFANA_URL}"
else
  echo "grafana | DOWN | no response on /api/health"
fi
