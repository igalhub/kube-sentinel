#!/usr/bin/env bash
# Project-specific service health checks for kube-sentinel.
# Each check prints: SERVICE_NAME | STATUS | detail
# STATUS: UP or DOWN

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

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

# --- Terraform state drift ---
# Intentional exception to the "<5s total" dev-check guideline: this check
# takes ~5s on its own. Measured -refresh=false at the same ~5s as a full
# refresh -- the Helm provider queries live Helm release state during
# planning regardless of Terraform's own -refresh flag, so skipping refresh
# buys no speed here. Full refresh is used because config-vs-actual-cluster
# drift (not just config-vs-stored-state) is exactly the failure class this
# check exists to catch.
TF_PLAN_OUTPUT=$(terraform -chdir="${REPO_ROOT}/terraform" plan -no-color -detailed-exitcode 2>&1)
TF_EXIT=$?
case "$TF_EXIT" in
  0)
    echo "terraform | UP | no drift, matches live cluster state"
    ;;
  2)
    TF_SUMMARY=$(echo "$TF_PLAN_OUTPUT" | grep -E "^  # " | sed 's/^  # /* /' | tr '\n' ' ')
    echo "terraform | DOWN | drift detected: ${TF_SUMMARY}"
    ;;
  *)
    echo "terraform | DOWN | terraform plan failed (not initialized, or a config error) -- run terraform init in terraform/"
    ;;
esac
