# SPEC — kube-sentinel

Technical spec of the current implementation. `docs/PRD.md` covers the
problem/goals/scope; this covers the exporter's internals, exact metric
shapes, and the Terraform/Helm deployment mechanics.

---

## Module map

```
exporter/main.py         entry point: k8s client setup, HTTP server, signal handling
exporter/collector.py     PodCollector, NodeCollector, DeploymentCollector
terraform/                provisions the cluster-facing resources (RBAC, namespace, Helm release)
helm/                     the Kubernetes manifests templated and applied by Terraform
```

## `exporter/main.py`

Config loading tries in-cluster ServiceAccount config first
(`k8s_config.load_incluster_config()`), falling back to local
`~/.kube/config` on `ConfigException` — the same binary works unmodified
in-cluster and against a local dev cluster (minikube/k3s).

`KubeSentinelCollector` is a custom Prometheus collector (registered
directly with a fresh `CollectorRegistry`, not the global default
registry — keeps this process's metrics isolated from any other
prometheus_client usage in the same interpreter). Its `collect()`
delegates to three sub-collectors in sequence, timing the total scrape
and appending three self-observability metrics after:

- `kube_sentinel_scrape_duration_seconds` — wall time for the whole scrape
- `kube_sentinel_scrape_errors_total` — summed error count across all
  three sub-collectors
- `kube_sentinel_up` — `0` if *any* sub-collector errored that scrape,
  `1` otherwise. This is a scrape-level health signal distinct from
  `kube_sentinel_node_ready`/`pod_ready` (which report the health of
  what's being monitored, not the monitor itself).

Scraping is pull-based, driven entirely by Prometheus's own scrape
interval hitting `:8080/metrics` — there's no internal polling loop.
`KUBE_SENTINEL_PORT` (default `8080`) and `KUBE_SENTINEL_NAMESPACES`
(comma-separated allowlist, empty = all namespaces) are the only two
env vars the exporter reads. `SIGTERM`/`SIGINT` are trapped for clean
shutdown (`threading.Event`), which matters for a fast pod termination
under Kubernetes' default grace period.

## `exporter/collector.py`

Three collectors, each returning `(list[Metric], error_count)` — a
`kubernetes.client.exceptions.ApiException` on any single collector's
list call is caught, logged, and turned into `error_count=1` for that
collector rather than propagating and killing the whole scrape. One
collector's API hiccup never takes down the metrics for the other two.

**`PodCollector`** — `list_pod_for_all_namespaces()`, optionally
filtered by `namespaces` allowlist post-fetch (not a server-side
filter, since a single all-namespaces list call is cheaper than N
per-namespace calls for a small cluster). Emits, per pod:

- `kube_sentinel_pod_phase{namespace,pod,phase}` — one row per phase
  in `_POD_PHASES` (`Pending`/`Running`/`Succeeded`/`Failed`/`Unknown`),
  `1.0` for the pod's actual phase, `0.0` for the rest — this
  "one-hot" encoding is what makes `phase="Pending"` queryable directly
  in PromQL without string matching.
- `kube_sentinel_pod_ready{namespace,pod}` — from the pod's `Ready`
  condition, defaulting to `0.0` if absent.
- `kube_sentinel_pod_restart_count{namespace,pod,container}` — per
  container, from `container_statuses[].restart_count`.
- `kube_sentinel_pod_container_state{namespace,pod,container,state,reason}` —
  one row per container reflecting whichever of
  `running`/`waiting`/`terminated` is currently set on
  `container.state`, with `reason` populated only for
  waiting/terminated (e.g. `CrashLoopBackOff`, `ErrImagePull`,
  `OOMKilled`).

**`NodeCollector`** — `list_node()` **and** `list_pod_for_all_namespaces()`
in the same collect() call, because per-node requested CPU/memory
isn't available directly on the Node object — it has to be summed from
every non-terminal pod's container resource requests, keyed by
`pod.spec.node_name`. Pods in `Succeeded`/`Failed` phase are excluded
from the sum (they're not consuming node resources anymore).
`_parse_cpu`/`_parse_memory` convert Kubernetes' quantity strings
(`"500m"`, `"2Gi"`, `"1000000000"`) to floats in cores/bytes — memory
suffixes are checked longest-first (`Gi` before `G`... actually `Ki`
before `K`, etc.) to avoid a binary suffix being misparsed as its
decimal counterpart. Emits allocatable and requested CPU/memory per
node, plus `kube_sentinel_node_ready` and
`kube_sentinel_node_condition{node,condition}` for the three pressure
conditions (`MemoryPressure`/`DiskPressure`/`PIDPressure`).

**`DeploymentCollector`** — `list_namespaced_deployment` or equivalent
across the namespace allowlist (or all namespaces), emits
`kube_sentinel_deployment_replicas_desired`/`_ready`/`_unavailable`.

## Metric naming convention

Every metric is prefixed `kube_sentinel_` — no bare metric names, so
this exporter's series never collide with `kube-state-metrics` or any
other exporter's output in the same Prometheus instance.

## Deployment: Terraform → Helm

```
terraform apply
  └── terraform/main.tf    — creates namespace, deploys the Helm chart as a
                             helm_release resource pointed at helm/
        └── helm/templates/
              ├── serviceaccount.yaml + clusterrole.yaml +
              │   clusterrolebinding.yaml  — RBAC: read-only (list/get)
              │   on pods, nodes, deployments across the cluster
              ├── deployment.yaml           — the exporter container
              └── service.yaml              — ClusterIP, port from
                                              helm/values.yaml, scraped
                                              by Prometheus via a
                                              ServiceMonitor/scrape config
```

`terraform/variables.tf` exposes the tunables (namespace, replica count,
image tag, `KUBE_SENTINEL_NAMESPACES` allowlist) as Terraform variables
rather than requiring direct edits to the Helm values file — one
`terraform apply` with variable overrides reconfigures the whole stack.
`terraform/outputs.tf` surfaces the deployed service endpoint and
namespace for use by the Prometheus/Grafana/Alertmanager pieces of the
stack.

RBAC is deliberately read-only: the ClusterRole grants `get`/`list`/`watch`
on pods, nodes, and deployments only — no write verbs anywhere, since
the exporter's entire job is observation.

## Polling model and its tradeoff

The exporter does not watch the Kubernetes API (`watch=True` streaming)
— every scrape does a fresh `list_*` call. This means up to one full
Prometheus scrape interval (typically 30s) of lag between a real state
change and it showing up in metrics. This is a deliberate simplicity
tradeoff over watch-based streaming, which is more responsive but
significantly more complex to implement correctly (resource version
tracking, reconnect/resync logic, stale-watch detection) — see
`docs/PRD.md`'s non-goals for the explicit call not to build that for
v1.
