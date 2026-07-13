terraform {
  required_version = ">= 1.0"
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.0"
    }
  }
}

provider "kubernetes" {
  config_path = var.kubeconfig_path
}

provider "helm" {
  kubernetes {
    config_path = var.kubeconfig_path
  }
}

# ---------------------------------------------------------------------------
# Namespace
# ---------------------------------------------------------------------------

resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = var.namespace
  }
}

# ---------------------------------------------------------------------------
# kube-sentinel exporter
# RBAC (ServiceAccount, ClusterRole, ClusterRoleBinding) is owned by the
# Helm chart — not duplicated here. Single source of truth for both manual
# helm install and terraform apply paths.
# ---------------------------------------------------------------------------

resource "helm_release" "kube_sentinel" {
  name      = "kube-sentinel"
  chart     = "${path.module}/../helm"
  namespace = kubernetes_namespace.monitoring.metadata[0].name

  wait    = true
  timeout = 120

  set {
    name  = "image.tag"
    value = var.kube_sentinel_image_tag
  }
  set {
    name  = "image.pullPolicy"
    value = var.kube_sentinel_image_pull_policy
  }
}

# ---------------------------------------------------------------------------
# Prometheus (minimal: server + Alertmanager, no node-exporter or kube-state-metrics)
# Deployed after kube-sentinel so the scrape target exists when Prometheus starts.
# ---------------------------------------------------------------------------

resource "helm_release" "prometheus" {
  name       = "prometheus"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "prometheus"
  version    = "29.13.0"
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  depends_on = [helm_release.kube_sentinel]

  wait    = true
  timeout = 300

  values = [
    templatefile("${path.module}/prometheus-values.yaml.tpl", {
      namespace       = var.namespace
      scrape_interval = var.scrape_interval
    }),
    # Alert rules loaded from alertmanager/rules.yaml — single source of truth.
    # yamldecode parses the file; yamlencode re-encodes it into the serverFiles structure.
    yamlencode({
      serverFiles = {
        "alerting_rules.yml" = yamldecode(file("${path.module}/../alertmanager/rules.yaml"))
      }
    })
  ]
}

# ---------------------------------------------------------------------------
# Grafana dashboard ConfigMap
# Created before the Grafana release so the sidecar finds it immediately.
# KS-005 replaces grafana/dashboard.json with real panels.
# ---------------------------------------------------------------------------

resource "kubernetes_config_map" "grafana_dashboard" {
  metadata {
    name      = "kube-sentinel-dashboard"
    namespace = kubernetes_namespace.monitoring.metadata[0].name
    labels = {
      grafana_dashboard = "1"
    }
  }

  data = {
    "kube-sentinel.json" = file("${path.module}/../grafana/dashboard.json")
  }
}

# ---------------------------------------------------------------------------
# Grafana (datasource pre-provisioned; dashboard loaded via sidecar ConfigMap)
# ---------------------------------------------------------------------------

resource "helm_release" "grafana" {
  name       = "grafana"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "grafana"
  version    = "10.5.15"
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  depends_on = [
    helm_release.prometheus,
    kubernetes_config_map.grafana_dashboard,
  ]

  wait    = true
  timeout = 300

  values = [
    templatefile("${path.module}/grafana-values.yaml.tpl", {
      namespace              = var.namespace
      grafana_admin_password = var.grafana_admin_password
    })
  ]
}
