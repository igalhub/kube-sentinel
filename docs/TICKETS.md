# TICKETS — kube-sentinel

Confirmed scope:
- Exporter: Python, kubernetes client, prometheus_client
- Metrics: pod health, node health, deployment health
- Polling: list (not watch), 30-second interval (configurable)
- Auth: in-cluster ServiceAccount (not kubeconfig)
- Infrastructure: Terraform + Helm (Prometheus minimal + Grafana)
- Testing: offline mocks + live minikube fixtures
- CI: GitHub Actions, offline suite only

Test marker: @pytest.mark.k8s for tests requiring a live cluster.

---

## KS-001 — Repo scaffolding, .gitignore, LICENSE, directory skeleton

**Status:** DONE
**Depends on:** nothing

**Description:**
Establish the repository baseline. No application logic. No credentials.

**Acceptance criteria:**
- [x] `.gitignore` excludes: `.idea/`, `.venv/`, `__pycache__/`, `*.pyc`,
      `*.pyo`, `.env`, `.terraform/`, `*.tfstate`, `*.tfstate.backup`,
      `*.tfvars`, `.terraform.lock.hcl`
- [x] `LICENSE` — MIT, copyright Igal Vexler 2026
- [x] `README.md` — full content from PRD package (not a placeholder)
- [x] `PRD.md`, `TICKETS.md`, `CLAUDE.md` in repo root
      (`PRD.md`/`TICKETS.md` later reorganized into `docs/`; `CLAUDE.md`
      and `README.md` remain at repo root)
- [x] Directory skeleton: `exporter/`, `terraform/`, `terraform/modules/`,
      `helm/`, `helm/templates/`, `tests/`, `docs/`, `grafana/`,
      `alertmanager/`
- [x] `requirements.txt` — pinned runtime deps:
      `kubernetes`, `prometheus_client`
- [x] `requirements-dev.txt` — pinned dev deps:
      `pytest`, `pytest-cov`
- [x] `config/` with `values.yaml.example` documenting all configurable
      parameters (scrape interval, namespaces to monitor, etc.)
- [x] `git status` after commit shows clean tree — no `.terraform/`,
      `.tfstate`, `.idea/`, `.venv/` untracked
- [x] Verified with `git log --stat`

---

## KS-002 — Exporter core: K8s API client + metric collectors

**Status:** DONE
**Depends on:** KS-001

**Description:**
The heart of the project. A Python service that connects to the K8s API
via in-cluster ServiceAccount auth, scrapes pod/node/deployment state,
and exposes results as Prometheus metrics on `/metrics`.

**Acceptance criteria:**
- [x] `exporter/collector.py` exports:
      - `PodCollector(client, namespaces)` — scrapes all pods
      - `NodeCollector(client)` — scrapes all nodes
      - `DeploymentCollector(client, namespaces)` — scrapes all deployments
      Each collector implements `collect()` returning prometheus_client
      metric objects
- [x] `exporter/main.py` — entry point:
      - connects via `kubernetes.config.load_incluster_config()` when
        running in-cluster
      - falls back to `load_kube_config()` when running locally (for
        development against minikube)
      - starts HTTP server on configurable port (default 8080)
      - registers all three collectors
- [x] Pod metrics implemented exactly as specified in PRD metrics reference:
      `kube_sentinel_pod_restart_count`, `kube_sentinel_pod_ready`,
      `kube_sentinel_pod_phase`, `kube_sentinel_pod_container_state`
- [x] Node metrics implemented: `kube_sentinel_node_ready`,
      `kube_sentinel_node_condition`, `kube_sentinel_node_allocatable_*`,
      `kube_sentinel_node_requested_*`
- [x] Deployment metrics implemented: `kube_sentinel_deployment_replicas_*`
- [x] Exporter self-metrics: `kube_sentinel_scrape_duration_seconds`,
      `kube_sentinel_scrape_errors_total`, `kube_sentinel_up`
- [x] All K8s API errors caught and reflected in `kube_sentinel_scrape_errors_total`
      — never crash the exporter on a single scrape failure
- [x] **Offline tests** (`tests/test_collectors.py`, `-m "not k8s"`):
      - mock the K8s API client
      - for each collector: a healthy object returns correct metric values,
        a broken object (crash-looping pod, node under pressure, deployment
        with unavailable replicas) returns correct metric values
      - all label sets correctly populated
- [x] **Live tests** (`-m k8s`):
      - deploy a crash-looping pod fixture (exits immediately)
      - confirm `kube_sentinel_pod_restart_count` > 0 and
        `kube_sentinel_pod_container_state{reason="CrashLoopBackOff"}` == 1
        after N restarts — **shown with actual /metrics output, not assumed**
      - deploy a deployment with 0 available replicas
      - confirm `kube_sentinel_deployment_replicas_unavailable` > 0
      - all fixtures cleaned up after tests
- [x] `pytest -m "not k8s" -v` passes with 0 failures
- [x] `pytest -m k8s -v` passes against live minikube —
      Developer runs this and shows full output

---

## KS-003 — Dockerfile + Helm chart

**Status:** DONE
**Depends on:** KS-002

**Description:**
Package the exporter as a container and write the Helm chart that
deploys it onto the cluster with correct RBAC.

**Acceptance criteria:**
- [x] `Dockerfile` — multi-stage build:
      - build stage: install deps
      - runtime stage: python:3.12-slim, non-root user, copies only
        what's needed
- [x] `helm/Chart.yaml` — name: kube-sentinel, version: 0.1.0
      (bumped to 0.1.1 post-completion when the readinessProbe was added)
- [x] `helm/values.yaml` — configurable: image tag, scrape interval,
      port, namespaces to monitor, resource limits
- [x] `helm/templates/deployment.yaml` — mounts ServiceAccount token,
      sets resource requests/limits, liveness probe on `/metrics`
- [x] `helm/templates/serviceaccount.yaml` — dedicated ServiceAccount
- [x] `helm/templates/clusterrole.yaml` — read-only access to pods,
      nodes, deployments (get, list, watch — principle of least privilege)
- [x] `helm/templates/clusterrolebinding.yaml` — binds the ClusterRole
      to the ServiceAccount
- [x] `helm/templates/service.yaml` — ClusterIP, port 8080
- [x] `docker build -t kube-sentinel:latest .` succeeds
- [x] `helm install kube-sentinel ./helm --set image.tag=latest`
      deploys successfully to minikube — verified with
      `kubectl get pods -n monitoring` showing Running
- [x] `curl $(minikube service kube-sentinel -n monitoring --url)/metrics`
      returns Prometheus-format output with all expected metric names
      — **actual output shown, not assumed**
- [x] ClusterRole uses minimum necessary permissions — no write access,
      no secrets access

---

## KS-004 — Terraform: provision full monitoring stack

**Status:** DONE
**Depends on:** KS-003

**Description:**
Terraform code that provisions the complete monitoring stack onto
minikube in one `terraform apply`. Uses the kubernetes and helm
Terraform providers.

**Acceptance criteria:**
- [x] `terraform/main.tf` provisions:
      - `monitoring` namespace
      - RBAC resources (can reference the Helm chart's templates or
        provision separately — Developer's choice, justify the decision)
      - Helm release: prometheus-community/prometheus (minimal values —
        no node-exporter, no kube-state-metrics, just Prometheus +
        Alertmanager)
      - Helm release: grafana/grafana (with pre-provisioned datasource
        and dashboard via values)
      - Helm release: kube-sentinel (local chart)
- [x] `terraform/variables.tf` — at minimum: kubeconfig path, namespace,
      image tag, scrape interval
- [x] `terraform/outputs.tf` — service URLs for Grafana, Prometheus,
      kube-sentinel
- [x] `terraform init` succeeds on a clean directory
- [x] `terraform plan` shows only expected resources, no surprises
- [x] `terraform apply` from a clean minikube cluster completes
      successfully — **all pods Running shown with `kubectl get pods -n monitoring`**
- [x] Grafana accessible via `minikube service grafana -n monitoring --url`
      — verified with actual browser/curl access
- [x] Prometheus accessible and scraping kube-sentinel — verified by
      querying `kube_sentinel_up` in the Prometheus UI and showing == 1
- [x] `terraform destroy` tears everything down cleanly — no orphaned
      resources left behind, verified with
      `kubectl get all -n monitoring` showing empty
- [x] No credentials, kubeconfig contents, or sensitive values committed
      to git — `.tfvars` and `.tfstate` gitignored

---

## KS-005 — Grafana dashboard + Alertmanager rules

**Status:** DONE
**Depends on:** KS-004

**Description:**
Pre-built Grafana dashboard JSON and Alertmanager alert rules, both
provisioned automatically via Terraform (as ConfigMaps or Helm values).
Not optional extras — a monitoring tool without dashboards and alerts
is half a tool.

**Acceptance criteria:**
- [x] `grafana/dashboard.json` — panels covering:
      - Pod restart count by namespace/pod (time series)
      - Pod phase distribution (stat panels: Running / Pending / Failed)
      - Container state reasons (CrashLoopBackOff, OOMKilled counts)
      - Deployment availability (desired vs available vs ready)
      - Node conditions (Ready, MemoryPressure, DiskPressure)
      - Node resource saturation (requested vs allocatable)
- [x] `alertmanager/rules.yaml` — alert rules covering at minimum:
      - `PodCrashLooping`: restart count > 5 in last 5 minutes
      - `NodeNotReady`: node_ready == 0 for > 1 minute
      - `NodeMemoryPressure`: node_condition{condition="MemoryPressure"} == 1
      - `DeploymentUnavailable`: replicas_unavailable > 0 for > 2 minutes
- [x] Dashboard provisioned automatically — visible in Grafana after
      `terraform apply`, no manual import required
- [x] Alert rules loaded in Alertmanager — verified by querying
      Alertmanager's `/api/v1/rules` endpoint
- [x] **Live proof:** deploy a crash-looping pod, wait for
      `PodCrashLooping` alert to fire in Alertmanager — show the
      actual alert in Alertmanager UI or API response
- [x] Dashboard panels display real data from the live cluster —
      screenshot taken and saved to `docs/screenshot.png`

---

## KS-006 — CI pipeline (GitHub Actions)

**Status:** DONE
**Depends on:** KS-002

**Description:**
GitHub Actions workflow running the offline test suite on every push
and PR. Live K8s tests are explicitly excluded from CI (no cluster
available on standard runners).

**Acceptance criteria:**
- [x] `.github/workflows/ci.yml` triggers on push and PR to `master`
- [x] Steps: checkout → Python 3.12 → install deps → pytest `-m "not k8s" -v`
- [x] CI passes on a clean push — actual Actions log read and confirmed
- [x] No credentials, kubeconfig, or cluster details in workflow file
      or CI logs
- [x] CI badge added to README

---

## KS-007 — README finalization + pre-publish audit

**Status:** DONE
**Depends on:** KS-005, KS-006

**Description:**
README is substantially complete from KS-001. This ticket is a
verification pass and finalization — plus the pre-publish security
audit which belongs to the user alone.

**Acceptance criteria (Developer):**
- [x] README accurately reflects final implementation — no placeholder
      text, no TODO lines, no steps that don't work as written
- [x] `eval $(minikube docker-env)` step is clearly documented and
      explained — easy to miss and breaks the build silently if skipped
- [x] Fresh-clone smoke test: clone into a fresh directory, follow
      README exactly, confirm `terraform apply` succeeds and Grafana
      dashboard loads — directory left intact for user to verify
- [x] Platform support table matches actual test results

**Acceptance criteria (User — not delegatable):**
- [x] `git log --all --full-history -- '*.tfvars' '*.tfstate' '*.env'`
      — confirm no sensitive files ever committed
- [x] `git log -p | grep -iE 'password|secret|token|kubeconfig'`
      — scan full patch history
- [x] Fresh-clone smoke test from a clean directory
- [x] Confirm `.terraform/`, `*.tfstate`, `*.tfstate.backup` absent
      from the published repo
- [x] CI badge is green on master

---

## KS-008 — Home lab deployment documentation

**Goal:** Document deployment on a Proxmox home lab environment using
k3s instead of minikube, including key differences and multi-project
coexistence.

**Deliverables:**
- `docs/HOMELAB_DEPLOYMENT.md` — full deployment walkthrough for
  Proxmox VE + Ubuntu Server VM + k3s environment
- README platform support table updated with k3s row
- README platform support note added for home lab
- Documented: k3s uses containerd — image import via
  `docker save | sudo k3s ctr images import` required
- Documented: NodePort access replaces `minikube service` commands
- Documented: Terraform outputs still reference minikube — use
  `kubectl get svc -n monitoring` instead

**Tested on:**
- Proxmox VE 9.2.3, Beelink SER mini PC
- Ubuntu Server 24.04.3 LTS VM
- k3s v1.35.5, Terraform 1.15.7, Helm 3.21.2, Docker 29.6.0

**Dependencies:** KS-007

**Status: DONE**

---

## Backlog (proposed — not scheduled)

Candidates surfaced during 2026-07-15 review. All four (KS-009, KS-010,
KS-011, KS-012) accepted and shipped — this backlog is now cleared.

### KS-009 — Windowed CrashLoopBackOff/OOMKilled panel queries

**Status:** DONE
**Depends on:** KS-005

Verified: `grafana/dashboard.json` panels "CrashLoopBackOff Containers"
(line 174) and "OOMKilled Containers" (line 210) still use instant
queries — `count(kube_sentinel_pod_container_state{state="waiting",
reason="CrashLoopBackOff"} == 1) or vector(0)` and the terminated/OOMKilled
equivalent — confirmed against the label names actually emitted by
`PodCollector.collect()` in `exporter/collector.py`. The PR #8 doc pass
added a description explaining the point-in-time gap rather than closing
it; `alertmanager/rules.yaml`'s `PodCrashLooping` rule already uses a more
robust `increase(...[5m])` pattern for the same underlying signal.

**Proposed fix:** change both panel expressions to
`max_over_time(kube_sentinel_pod_container_state{...}[5m])` (or similar)
so a container that cycled through the state within the window still
shows up.

**Acceptance criterion:** both panels stay non-zero for the full 5m
window after a fixture pod enters CrashLoopBackOff/OOMKilled once, even
after the container transitions to a different state.

**Shipped:** commit `05c893d` (PR #12). Both panel descriptions rewritten
to describe the new trailing-positive behavior (stays red up to 5m after
recovery) instead of the old point-in-time false-negative caveat.
Verified live against a `crashloop-test` fixture: caught the container in
`terminated/Error` state where the old instant query read 0, confirmed
the windowed query held at 1 through that gap and after the container
returned to `CrashLoopBackOff`.

---

### KS-010 — CI/pre-commit check for unpinned helm_release versions

**Status:** DONE
**Depends on:** none

Verified: `terraform/main.tf` — `helm_release.prometheus` (line 69) and
`helm_release.grafana` (line 120) pin explicit `version` attributes
(fixed in ba6c9bb). `helm_release.kube_sentinel` (line 42) has no
`version` attribute, but this is not an instance of the same bug — it
points at a local chart path (`chart = "${path.module}/../helm"`), which
has no separate registry version to pin; the chart's own version lives
in `helm/Chart.yaml`. A naive "every helm_release needs a version"
check would false-positive on this block.

**Proposed fix:** a grep-based check (pre-commit or CI step) that fails
if any `helm_release` block with a `repository` attribute lacks a
sibling `version` attribute — scoped to repo-based charts only, not
local-path charts.

**Acceptance criterion:** the check fails on a deliberately-introduced
unpinned repo-based `helm_release` block, and passes on the current
`terraform/main.tf` unmodified.

**Shipped:** commit `6492a31` (PR #13). Implemented with a real HCL2
parser (`python-hcl2`) rather than grep — the Explore/Plan pass found
that `terraform/main.tf`'s blocks contain nested `values=[...]` lists
with their own braces, nested `set{}` blocks, and inline comments, none
of which a regex/brace-counter could handle reliably. `kube_sentinel` is
exempt by construction (no `repository` attribute), not by a hardcoded
exclusion. New script `scripts/check_helm_versions.py`, wired into
`.github/workflows/ci.yml`, with `tests/test_check_helm_versions.py`
covering all four cases. Mutation-tested live: removed `version` from
`helm_release.prometheus`, confirmed the check failed naming the exact
block, reverted, confirmed a clean pass; also mutation-tested the new
unit tests themselves by breaking the resource-type filter.

---

### KS-011 — dev-check.sh: Terraform state drift check

**Status:** DONE
**Depends on:** none

Verified: `.claude/dev-check.sh` currently only checks minikube status
and HTTP reachability of the exporter/Prometheus/Grafana services — no
Terraform plan/state check exists.

**Proposed fix:** add a check that runs `terraform plan -detailed-exitcode`
(or equivalent) from `terraform/` and reports DOWN if it would
create/destroy/modify anything, rather than only checking service
reachability.

**Acceptance criterion:** with a deliberately `terraform state rm`'d
resource, `dev-check.sh` reports the Terraform check as DOWN with the
drift detail; on a clean apply it reports UP.

**Shipped:** commit `d7197ab` (PR #14). Two design decisions resolved
during Explore/Plan rather than assumed: (1) full refresh is used, not
`-refresh=false` — both measured at ~5.3s since the Helm provider
queries live release state during planning regardless of the refresh
flag, so skipping refresh buys no speed but would miss real
config-vs-actual-cluster drift; (2) the check distinguishes "not
initialized" (any exit code other than 0/2) from "drift detected" (exit
2) with different messages, verified in an isolated `/tmp` copy of
`terraform/` without touching the real working state. This pushes
`dev-check.sh`'s total runtime past the project's own documented <5s
guideline for checks — a deliberate, commented exception. Mutation-
tested live via `kubectl label` (real outside-Terraform drift, not
`terraform state rm` as originally proposed) on the Grafana dashboard
ConfigMap: confirmed DOWN naming the exact resource, reverted, confirmed
clean UP again. This is the last item from the 2026-07-15 backlog
review — KS-009, KS-010, KS-011, and KS-012 are all now shipped.

---

### KS-012 — Node CPU/Memory Saturation alert rules

**Status:** DONE
**Depends on:** KS-005

Verified: `grafana/dashboard.json` "Node CPU Saturation" (line 424) and
"Node Memory Saturation" (line 465) panels both use yellow@70 / red@90
visual thresholds against requested-vs-allocatable ratios. No
corresponding rule exists in `alertmanager/rules.yaml` — the four
existing rules (`PodCrashLooping`, `NodeNotReady`, `NodeMemoryPressure`,
`DeploymentUnavailable`) don't cover CPU/memory saturation ratios. This
is the only pair of dashboard panels with visual alert thresholds that
isn't backed by a paging rule.

**Proposed fix:** add `NodeCPUSaturation` / `NodeMemorySaturation` alert
rules to `alertmanager/rules.yaml`, mirroring the dashboard's 90% (red)
threshold using `kube_sentinel_node_requested_*` /
`kube_sentinel_node_allocatable_*`.

**Acceptance criterion:** a node fixture pushed above 90% requested/
allocatable ratio fires the alert, verified via Alertmanager's
`/api/v1/rules` or `/api/v1/alerts` endpoint.

**Shipped:** commit `8b5822f` (PR #11). Implemented with
`severity: warning` and `for: 5m` on both rules — warning (not
critical) to stay consistent with the existing non-boolean rules in
`alertmanager/rules.yaml` (only `NodeNotReady` is critical); 5m is a
sustained-signal window rather than an instant fire, since saturation
is a trend rather than a boolean condition flip. Verified live against
Prometheus `/api/v1/rules` (both rules `health: ok`, no `lastError`)
and confirmed correctly inactive against the live node at ~7% CPU /
~0.7% memory saturation.

---

## KS-stretch-01 — PersistentVolume health metrics

**Status:** DEFERRED

PV bound/released/failed state monitoring. Deferred to v2 — not all
clusters use PVs and it adds meaningful K8s API complexity.

---

## KS-stretch-02 — Watch-based streaming (replace polling)

**Status:** DEFERRED

Replace list-based polling with watch-based streaming for real-time
(sub-second) failure detection. Significantly more complex reconciliation
loop. Deferred to v2.

---

## KS-stretch-03 — Managed cloud cluster support (EKS/GKE/AKS)

**Status:** DEFERRED

Cloud-provider-specific Terraform modules for provisioning on managed
clusters. Each provider requires different IAM, VPC, and node group
configuration. Deferred — out of scope for a minikube-first project.

---

## Ticket status

| Ticket | Title | Status |
|---|---|---|
| KS-001 | Repo scaffolding | DONE |
| KS-002 | Exporter core + collectors | DONE |
| KS-003 | Dockerfile + Helm chart | DONE |
| KS-004 | Terraform: full monitoring stack | DONE |
| KS-005 | Grafana dashboard + Alertmanager rules | DONE |
| KS-006 | CI pipeline | DONE |
| KS-007 | README finalization + audit | DONE |
| KS-008 | Home lab deployment documentation | DONE |
| KS-009 | Windowed CrashLoopBackOff/OOMKilled panel queries | DONE |
| KS-010 | CI check for unpinned helm_release versions | DONE |
| KS-011 | dev-check.sh Terraform state drift check | DONE |
| KS-012 | Node CPU/Memory Saturation alert rules | DONE |
| KS-stretch-01 | PV health metrics | DEFERRED |
| KS-stretch-02 | Watch-based streaming | DEFERRED |
| KS-stretch-03 | Managed cloud support | DEFERRED |
