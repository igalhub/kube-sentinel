# PRD — kube-sentinel

A Kubernetes cluster health exporter that surfaces pod, node, and
deployment health as Prometheus metrics, with pre-built Grafana
dashboards and Alertmanager rules. Deployed onto a cluster via
Terraform + Helm. Fourth in a series of silent-failure detectors
alongside Vault Secrets Demo, Expiry Watcher, and docker-sentinel.

---

## Who this is for

**Primary audience:** small engineering teams or solo developers running
a Kubernetes cluster (on-prem, minikube, or a managed cloud cluster)
without a full commercial observability stack. Specifically:

- A startup running 10–50 pods on a single-node or small cluster who
  want to know when things are silently broken without paying for
  Datadog or New Relic
- A platform engineer setting up internal tooling who wants a
  lightweight, self-hosted monitoring baseline
- A DevOps engineer evaluating whether Prometheus/Grafana is the right
  fit for their team before committing to a full observability stack

**Not the primary audience:**
- Teams already running kube-prometheus-stack, Datadog, or a managed
  observability solution — they already have this covered
- Teams running large clusters (100+ nodes) where a minimal exporter
  would need significant extension to be useful

---

## The problem

Kubernetes has built-in health primitives — liveness probes, readiness
probes, restart policies, resource limits — but surfacing them in a
useful, proactive way requires either:

1. Running `kubectl` commands manually and knowing what to look for
2. Setting up a full commercial observability stack ($500+/month)
3. Deploying kube-prometheus-stack — which is powerful but complex,
   with ~40 CRDs, multiple operators, and significant operational
   overhead for a small team

The gap this fills: a small team running a cluster wants to know when
a pod is crash-looping, a node is under memory pressure, or a
deployment has unavailable replicas — without having to either watch
`kubectl get pods` or operate a full Prometheus ecosystem from scratch.

### Silent failures Kubernetes hides from you

| Problem | What `kubectl get pods` shows | What's actually happening |
|---|---|---|
| CrashLoopBackOff | "Running" briefly, then "Error", repeat | Container exits immediately, K8s keeps restarting it |
| OOMKilled | Pod restarts, no obvious cause | Container hit memory limit and was killed by the kernel |
| Pending pods | "Pending" indefinitely | Can't be scheduled — insufficient resources, wrong node selector, or PVC not bound |
| Failed readiness probe | "Running" but receiving no traffic | App started but isn't ready — DB connection failed, health endpoint returning non-200 |
| Image pull errors | "ErrImagePull" or "ImagePullBackOff" | Wrong image tag, private registry auth missing |
| Evicted pods | Pod gone with no warning | Node ran out of disk or memory, K8s evicted it silently |
| Node pressure | Pods occasionally fail for no obvious reason | Node is under MemoryPressure or DiskPressure — K8s is making decisions based on this |
| Unavailable replicas | Deployment looks fine | Desired replica count not met — some pods failing to start |

All of these are detectable from the K8s API. None of them proactively
alert you without a monitoring setup.

---

## Goals

- G1: Export pod health metrics — restart count, phase, ready status,
  container state (running/waiting/terminated), reason for waiting
  (CrashLoopBackOff, OOMKilled, ErrImagePull, etc.)
- G2: Export node health metrics — Ready condition, MemoryPressure,
  DiskPressure, PIDPressure, allocatable vs requested resources
- G3: Export deployment health metrics — desired vs available vs
  ready replicas, unavailable replica count
- G4: Expose all metrics on a `/metrics` endpoint in standard
  Prometheus text format — compatible with any Prometheus scraper
- G5: Provision the full monitoring stack (Prometheus + Grafana +
  exporter) onto a Kubernetes cluster via Terraform + Helm — one
  `terraform apply` from zero to working dashboards
- G6: Ship pre-built Grafana dashboard JSON and Alertmanager rules
  covering the most important failure patterns
- G7: All thresholds and scrape intervals configurable via Helm values
- G8: Tested end-to-end on minikube; behavior on managed cloud clusters
  documented honestly as untested

---

## Non-goals (v1)

- **PersistentVolume / PVC health** — PV bound/released/failed state is
  a legitimate monitoring target but adds meaningful complexity and is
  not universally applicable (not all clusters use PVs). Deferred to v2.
- **Custom resource definitions (CRDs)** — monitoring CRD state
  (e.g. ArgoCD Application health) requires per-CRD integration.
  Out of scope.
- **Multi-cluster monitoring** — monitors a single cluster only.
  Multi-cluster aggregation is a fundamentally different architecture.
- **Log aggregation** — metrics only. Logs (EFK/Loki stack) are a
  separate concern and a separate project.
- **Auto-remediation** — detects and surfaces, never restarts pods or
  cordons nodes automatically. Auto-remediation carries real risks and
  belongs in a separate, explicitly-scoped tool.
- **Commercial managed clusters (EKS/GKE/AKS)** — the exporter itself
  is cluster-agnostic, but the Terraform provisioning is written and
  tested for minikube only. Managed cluster provisioning (VPC, node
  groups, IAM) is not in scope.
- **Horizontal Pod Autoscaler metrics** — HPA state monitoring is a
  natural v2 addition once core pod/node/deployment health is solid.

---

## What this tool detects (v1 metric set)

### Pod metrics

```
kube_sentinel_pod_restart_count{namespace, pod, container}
kube_sentinel_pod_ready{namespace, pod}                          # 0 or 1
kube_sentinel_pod_phase{namespace, pod, phase}                   # 0 or 1 per phase
kube_sentinel_pod_container_state{namespace, pod, container, state, reason}
```

`state` values: `running`, `waiting`, `terminated`
`reason` values (for waiting): `CrashLoopBackOff`, `OOMKilled`,
`ErrImagePull`, `ImagePullBackOff`, `ContainerCreating`, etc.

### Node metrics

```
kube_sentinel_node_ready{node}                                   # 0 or 1
kube_sentinel_node_condition{node, condition}                    # 0 or 1 per condition
kube_sentinel_node_allocatable_cpu_cores{node}
kube_sentinel_node_allocatable_memory_bytes{node}
kube_sentinel_node_requested_cpu_cores{node}
kube_sentinel_node_requested_memory_bytes{node}
```

`condition` values: `MemoryPressure`, `DiskPressure`, `PIDPressure`

### Deployment metrics

```
kube_sentinel_deployment_replicas_desired{namespace, deployment}
kube_sentinel_deployment_replicas_available{namespace, deployment}
kube_sentinel_deployment_replicas_ready{namespace, deployment}
kube_sentinel_deployment_replicas_unavailable{namespace, deployment}
```

### Exporter self-metrics (standard)

```
kube_sentinel_scrape_duration_seconds
kube_sentinel_scrape_errors_total
kube_sentinel_up                                                 # 1 if last scrape succeeded
```

---

## Architecture

```
Kubernetes cluster (minikube)
  │
  ├── kube-sentinel (Deployment, 1 replica)
  │     └── Python service
  │           ├── kubernetes Python client — connects via in-cluster
  │           │   ServiceAccount (not kubeconfig — portable)
  │           ├── scrapes K8s API every 30s (configurable)
  │           │     ├── list pods (all namespaces)
  │           │     ├── list nodes
  │           │     └── list deployments (all namespaces)
  │           └── exposes GET /metrics → Prometheus text format
  │
  ├── Prometheus (Helm: prometheus-community/prometheus)
  │     └── scrapes kube-sentinel /metrics every 30s via ServiceMonitor
  │
  ├── Grafana (Helm: grafana/grafana)
  │     ├── pre-provisioned datasource → Prometheus
  │     └── pre-provisioned dashboard → kube-sentinel panels
  │
  └── Alertmanager (bundled with Prometheus chart)
        └── pre-configured alert rules → CrashLoopBackOff, node pressure,
            unavailable replicas

Terraform (local, not in-cluster)
  └── manages the above via kubernetes + helm Terraform providers
        ├── namespace creation
        ├── RBAC (ServiceAccount, ClusterRole, ClusterRoleBinding)
        ├── Helm releases (prometheus, grafana, kube-sentinel)
        └── ConfigMaps (Grafana dashboard JSON, Alertmanager rules)
```

### Why in-cluster ServiceAccount, not kubeconfig?

A pod running inside the cluster authenticates to the K8s API via a
mounted ServiceAccount token — no kubeconfig file needed, no credentials
to manage, works identically on minikube and any managed cluster. This
is the correct, production-appropriate pattern. kubeconfig-based auth
is for out-of-cluster tools (kubectl, Terraform's kubernetes provider).

### Why minimal Prometheus stack, not kube-prometheus-stack?

kube-prometheus-stack installs ~40 CRDs, multiple operators
(prometheus-operator, node-exporter, kube-state-metrics), and many
components that would dwarf the exporter itself. For a focused
portfolio project demonstrating a custom exporter, a minimal
Prometheus + Grafana installation is cleaner, easier to understand,
and more honest about what the project actually does. The README
explicitly documents this tradeoff.

---

## Tech stack

| Component | Technology | Why |
|---|---|---|
| Exporter | Python, `kubernetes` client, `prometheus_client` | Official K8s Python client; prometheus_client handles metric format, registry, HTTP server |
| Container | Docker, multi-stage build | Standard deployment unit for K8s workloads |
| Provisioning | Terraform (kubernetes + helm providers) | IaC pattern, declarative, reproducible; demonstrates Terraform beyond just VM provisioning |
| Prometheus | Helm chart (prometheus-community/prometheus) | Standard minimal install, no operator overhead |
| Grafana | Helm chart (grafana/grafana) | Pre-provisioned dashboards via ConfigMap |
| Alertmanager | Bundled with Prometheus chart | Alert rules as code, committed to repo |
| Testing | pytest, unittest.mock | Mocked K8s API responses for offline tests; live minikube fixtures for integration tests |
| CI | GitHub Actions | Same pattern as all previous projects |

---

## Gaps this fills vs existing tools

| Tool | What it does | Gap kube-sentinel fills |
|---|---|---|
| `kubectl get pods` | Shows current state, manually | Not proactive, no alerting, no history |
| kube-prometheus-stack | Full monitoring suite | Complex to operate, ~40 CRDs, significant overhead for small teams |
| Datadog / New Relic | Commercial APM | $500+/month, not self-hosted |
| kube-state-metrics | Exposes K8s state as metrics | Requires Prometheus to be already running; no Grafana dashboards; no Alertmanager rules; not a complete solution |
| metrics-server | Resource usage metrics | CPU/memory only, no pod phase / container state / restart reasons |

kube-sentinel's position: a complete, self-contained, deployable
monitoring solution for small clusters that don't need the full
kube-prometheus-stack but want more than manual kubectl.

---

## Deployment (user-facing)

```bash
# Prerequisites: minikube running, kubectl configured, Terraform installed
git clone git@github.com:igalhub/kube-sentinel.git
cd kube-sentinel/terraform
terraform init
terraform apply   # deploys everything: Prometheus, Grafana, kube-sentinel
# Access Grafana: minikube service grafana --url
# Access Prometheus: minikube service prometheus-server --url
```

Teardown:
```bash
terraform destroy
```

---

## Success criteria

- `terraform apply` from a clean minikube cluster deploys all components
  and produces a working Grafana dashboard in under 5 minutes
- The exporter correctly surfaces: a CrashLoopBackOff pod, a node under
  MemoryPressure, and a deployment with unavailable replicas — all
  verified with real minikube fixtures
- Alertmanager fires a real alert for a CrashLoopBackOff pod — shown
  with actual output, not assumed
- Full test suite including live minikube fixtures for each metric type
- README documents exactly what's tested (minikube), what's untested
  (managed cloud clusters), and the architectural tradeoffs made

---

## Platform support

| Component | minikube | EKS/GKE/AKS | On-prem K8s |
|---|---|---|---|
| Exporter (in-cluster) | ✅ Tested | ⚠️ Should work — in-cluster SA auth is standard | ⚠️ Should work |
| Terraform provisioning | ✅ Tested | ❌ Not in scope — managed cluster provisioning differs significantly | ❌ Not in scope |
| Helm charts | ✅ Tested | ⚠️ Charts are standard — provisioning them via Terraform against a managed cluster is untested | ⚠️ Untested |

---

## Out of scope risks (explicitly documented)

- Single-node minikube only — not tested against multi-node clusters
  where pod scheduling across nodes changes some metric behaviors
- The exporter uses list (not watch) — polling every 30s means up to
  30s lag between a failure and it appearing in metrics. Watch-based
  streaming is more responsive but significantly more complex. Documented
  as a known limitation, not a bug.
- Grafana dashboards are pre-provisioned via ConfigMap — they cannot
  be edited and saved in the UI (changes would be lost on pod restart).
  This is intentional for reproducibility; documented in README.
