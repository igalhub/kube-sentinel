# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Current state

Project is complete. All tickets KS-001 through KS-007 implemented, QA-accepted, and committed. See TICKETS.md for the full sequence and acceptance criteria.

---

## Commands

**Setup:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

**Build the exporter image (must point Docker at minikube's daemon):**
```bash
eval $(minikube docker-env)
docker build -t kube-sentinel:latest .
```

**Run the exporter locally (against minikube):**
```bash
# Uses load_kube_config() fallback when not running in-cluster
python -m exporter.main
curl http://localhost:8080/metrics
```

**Deploy with Terraform:**
```bash
cd terraform
terraform init
terraform apply
terraform destroy   # teardown
```

**Access services:**
```bash
minikube service grafana -n monitoring --url
# Default credentials: admin / admin (change on first login)
minikube service prometheus-server -n monitoring --url
minikube service kube-sentinel -n monitoring --url
```

**Tests:**
```bash
# Offline suite — no cluster required (what CI runs):
pytest -m "not k8s" -v

# Live K8s suite — requires minikube running:
pytest -m k8s -v

# Single test file:
pytest tests/test_collectors.py -v
```

**Check cluster state:**
```bash
kubectl get pods -n monitoring
kubectl get pods -A
kubectl logs -n monitoring deployment/kube-sentinel
```

---

## Architecture

Two layers:

**Exporter (Python, runs inside the cluster):**
```
exporter/main.py          — entry point, HTTP server, metric registry
exporter/collector.py     — PodCollector, NodeCollector, DeploymentCollector
```

Each collector:
- takes a `kubernetes.client` instance
- implements `collect()` returning prometheus_client metric objects
- uses `list_pod_for_all_namespaces()`, `list_node()`,
  `list_deployment_for_all_namespaces()` — list (not watch), 30s interval
- catches all K8s API exceptions; increments
  `kube_sentinel_scrape_errors_total` rather than raising

Auth: `load_incluster_config()` when running as a pod (uses mounted
ServiceAccount token at `/var/run/secrets/kubernetes.io/serviceaccount/`);
falls back to `load_kube_config()` for local development.

**Infrastructure (Terraform + Helm, runs locally):**
```
terraform/main.tf         — namespace, RBAC, Helm releases
terraform/variables.tf    — kubeconfig path, namespace, image tag, etc.
terraform/outputs.tf      — service URLs
helm/                     — Helm chart for the exporter
grafana/dashboard.json    — pre-built Grafana dashboard
alertmanager/rules.yaml   — Alertmanager alert rules
config/values.yaml.example — all configurable parameters documented
```

**Test split:**
- `@pytest.mark.k8s` — requires live minikube cluster; creates real
  pod fixtures, confirms metrics fire correctly, cleans up after
- Everything else — mocks the K8s client; CI runs only offline tests
- The `k8s` marker must be registered in `pytest.ini` to avoid PytestUnknownMarkWarning

**Ticket implementation order:** KS-001 (scaffolding) → KS-002 (exporter core) →
KS-003 (Dockerfile + Helm) → KS-004 (Terraform) → KS-005 (dashboard + alerts) →
KS-006 (CI) → KS-007 (README audit). Each ticket depends on the previous.

---

## Claude Code Team Instructions

This project is built using three distinct roles. Explicitly state
which role you are acting as at the start of each response. Do not
blend roles in a single turn.

## Role: PM

Responsibilities:
- Own PRD.md and TICKETS.md
- Break PRD into tickets with acceptance criteria and dependencies
- Accept/reject based on QA's report; never write code
- Definition of done: QA has run the test suite AND proven that each
  metric correctly fires on a real broken K8s fixture — not just that
  the exporter runs without error

## Role: Developer

Responsibilities:
- Implement one ticket at a time
- Restate acceptance criteria before starting
- Write code + tests in the same pass
- Never self-approve
- All K8s API access via the official `kubernetes` Python client —
  no subprocess calls to `kubectl`, no shell commands, no string
  parsing of CLI output
- In-cluster ServiceAccount auth only — no kubeconfig hardcoded,
  no credentials in code

## Role: QA

Responsibilities:
- For every metric, prove both directions:
  - A healthy object produces the correct metric value
  - A broken object (crash-looping pod, node under pressure, etc.)
    produces the correct metric value — using a real K8s fixture,
    not a mock
- Confirm live fixtures are cleaned up after tests
- Confirm no credentials appear in any test file, log, or output
- Report: Ticket ID / tests run-passed-failed / fixture verification /
  ACCEPT-REJECT

## Shared rules

- No credentials, kubeconfig contents, or sensitive values committed
  to git — `.tfvars` and `.tfstate` are gitignored for this reason
- All K8s API access via the `kubernetes` Python client — no
  subprocess/CLI calls in exporter code or tests
- Live test fixtures must be real K8s objects created via the
  Python client — not mocked runtime state
- `eval $(minikube docker-env)` must be run before any `docker build`
  — failing to do this means the image is built locally but not
  available inside the cluster; this mistake is easy to make and
  hard to debug, so QA must verify the pod is actually using the
  correct image

---

For the general cross-project working process (verification discipline,
mutation testing, commit cadence, never-delegate checkpoints, etc.),
see the global modus operandi at ~/.claude/CLAUDE.md.
