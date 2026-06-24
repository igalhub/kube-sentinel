"""
Offline tests: mock the K8s API client — no cluster required.
Live tests:    @pytest.mark.k8s — require minikube running.
"""
import pytest
from unittest.mock import MagicMock
from kubernetes.client.exceptions import ApiException

from exporter.collector import DeploymentCollector, NodeCollector, PodCollector
from tests.conftest import wait_for


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample(metrics, metric_name, labels):
    """Return the value of a specific sample, or None if not found."""
    for m in metrics:
        if m.name == metric_name:
            for s in m.samples:
                if s.labels == labels:
                    return s.value
    return None


def _make_pod(
    namespace="default",
    name="test-pod",
    phase="Running",
    ready=True,
    containers=None,
    node_name="node1",
    spec_containers=None,
):
    pod = MagicMock()
    pod.metadata.namespace = namespace
    pod.metadata.name = name
    pod.spec.node_name = node_name
    pod.spec.containers = spec_containers or []

    pod.status.phase = phase
    pod.status.conditions = [_make_condition("Ready", "True" if ready else "False")]
    pod.status.container_statuses = containers or []
    return pod


def _make_condition(cond_type, status):
    c = MagicMock()
    c.type = cond_type
    c.status = status
    return c


def _make_container_status(name, restarts=0, state="running", reason=None):
    cs = MagicMock()
    cs.name = name
    cs.restart_count = restarts

    cs.state.running = None
    cs.state.waiting = None
    cs.state.terminated = None

    if state == "running":
        cs.state.running = MagicMock()
    elif state == "waiting":
        waiting = MagicMock()
        waiting.reason = reason
        cs.state.waiting = waiting
    elif state == "terminated":
        terminated = MagicMock()
        terminated.reason = reason
        cs.state.terminated = terminated

    return cs


def _make_node(name="node1", ready=True, conditions=None, allocatable=None):
    node = MagicMock()
    node.metadata.name = name

    conds = [_make_condition("Ready", "True" if ready else "False")]
    for cond_type, active in (conditions or {}).items():
        conds.append(_make_condition(cond_type, "True" if active else "False"))

    node.status.conditions = conds
    node.status.allocatable = allocatable or {"cpu": "2", "memory": "4Gi"}
    return node


def _make_deployment(
    namespace="default",
    name="test-deploy",
    desired=3,
    available=3,
    ready=3,
    unavailable=0,
):
    deploy = MagicMock()
    deploy.metadata.namespace = namespace
    deploy.metadata.name = name
    deploy.spec.replicas = desired
    deploy.status.available_replicas = available
    deploy.status.ready_replicas = ready
    deploy.status.unavailable_replicas = unavailable
    return deploy


def _pod_list(*pods):
    lst = MagicMock()
    lst.items = list(pods)
    return lst


def _node_list(*nodes):
    lst = MagicMock()
    lst.items = list(nodes)
    return lst


def _deploy_list(*deploys):
    lst = MagicMock()
    lst.items = list(deploys)
    return lst


# ---------------------------------------------------------------------------
# PodCollector — offline
# ---------------------------------------------------------------------------

class TestPodCollectorOffline:
    def _collector(self, *pods):
        v1 = MagicMock()
        v1.list_pod_for_all_namespaces.return_value = _pod_list(*pods)
        return PodCollector(v1)

    def test_healthy_running_pod(self):
        cs = _make_container_status("app", restarts=0, state="running")
        c = self._collector(_make_pod(containers=[cs]))
        metrics, errors = c.collect()

        assert errors == 0
        assert _sample(metrics, "kube_sentinel_pod_restart_count",
                       {"namespace": "default", "pod": "test-pod", "container": "app"}) == 0.0
        assert _sample(metrics, "kube_sentinel_pod_ready",
                       {"namespace": "default", "pod": "test-pod"}) == 1.0
        assert _sample(metrics, "kube_sentinel_pod_phase",
                       {"namespace": "default", "pod": "test-pod", "phase": "Running"}) == 1.0
        assert _sample(metrics, "kube_sentinel_pod_phase",
                       {"namespace": "default", "pod": "test-pod", "phase": "Pending"}) == 0.0
        assert _sample(metrics, "kube_sentinel_pod_container_state",
                       {"namespace": "default", "pod": "test-pod",
                        "container": "app", "state": "running", "reason": ""}) == 1.0

    def test_crashloop_pod(self):
        cs = _make_container_status(
            "app", restarts=5, state="waiting", reason="CrashLoopBackOff"
        )
        c = self._collector(_make_pod(ready=False, containers=[cs]))
        metrics, errors = c.collect()

        assert errors == 0
        assert _sample(metrics, "kube_sentinel_pod_restart_count",
                       {"namespace": "default", "pod": "test-pod", "container": "app"}) == 5.0
        assert _sample(metrics, "kube_sentinel_pod_ready",
                       {"namespace": "default", "pod": "test-pod"}) == 0.0
        assert _sample(metrics, "kube_sentinel_pod_container_state",
                       {"namespace": "default", "pod": "test-pod",
                        "container": "app", "state": "waiting",
                        "reason": "CrashLoopBackOff"}) == 1.0

    def test_oomkilled_pod(self):
        cs = _make_container_status(
            "app", restarts=1, state="terminated", reason="OOMKilled"
        )
        c = self._collector(_make_pod(containers=[cs]))
        metrics, errors = c.collect()

        assert errors == 0
        assert _sample(metrics, "kube_sentinel_pod_container_state",
                       {"namespace": "default", "pod": "test-pod",
                        "container": "app", "state": "terminated",
                        "reason": "OOMKilled"}) == 1.0

    def test_pending_pod(self):
        c = self._collector(_make_pod(phase="Pending", containers=[]))
        metrics, errors = c.collect()

        assert errors == 0
        assert _sample(metrics, "kube_sentinel_pod_phase",
                       {"namespace": "default", "pod": "test-pod", "phase": "Pending"}) == 1.0
        assert _sample(metrics, "kube_sentinel_pod_phase",
                       {"namespace": "default", "pod": "test-pod", "phase": "Running"}) == 0.0

    def test_api_error_returns_error_count(self):
        v1 = MagicMock()
        v1.list_pod_for_all_namespaces.side_effect = ApiException(status=403)
        c = PodCollector(v1)
        metrics, errors = c.collect()

        assert errors == 1
        assert metrics == []

    def test_namespace_filter(self):
        cs = _make_container_status("app", restarts=0, state="running")
        pod_a = _make_pod(namespace="prod", name="pod-a", containers=[cs])
        pod_b = _make_pod(namespace="staging", name="pod-b", containers=[cs])
        v1 = MagicMock()
        v1.list_pod_for_all_namespaces.return_value = _pod_list(pod_a, pod_b)
        c = PodCollector(v1, namespaces=["prod"])
        metrics, errors = c.collect()

        assert errors == 0
        assert _sample(metrics, "kube_sentinel_pod_ready",
                       {"namespace": "prod", "pod": "pod-a"}) == 1.0
        assert _sample(metrics, "kube_sentinel_pod_ready",
                       {"namespace": "staging", "pod": "pod-b"}) is None

    def test_all_phases_emitted_for_each_pod(self):
        c = self._collector(_make_pod(phase="Running", containers=[]))
        metrics, _ = c.collect()
        for phase in ("Pending", "Running", "Succeeded", "Failed", "Unknown"):
            val = _sample(metrics, "kube_sentinel_pod_phase",
                          {"namespace": "default", "pod": "test-pod", "phase": phase})
            assert val is not None, f"Phase {phase!r} not emitted"


# ---------------------------------------------------------------------------
# NodeCollector — offline
# ---------------------------------------------------------------------------

class TestNodeCollectorOffline:
    def _collector(self, nodes, pods=None):
        v1 = MagicMock()
        v1.list_node.return_value = _node_list(*nodes)
        v1.list_pod_for_all_namespaces.return_value = _pod_list(*(pods or []))
        return NodeCollector(v1)

    def test_healthy_node(self):
        c = self._collector([_make_node(allocatable={"cpu": "4", "memory": "8Gi"})])
        metrics, errors = c.collect()

        assert errors == 0
        assert _sample(metrics, "kube_sentinel_node_ready", {"node": "node1"}) == 1.0
        assert _sample(metrics, "kube_sentinel_node_allocatable_cpu_cores",
                       {"node": "node1"}) == 4.0
        assert _sample(metrics, "kube_sentinel_node_allocatable_memory_bytes",
                       {"node": "node1"}) == 8 * 1024**3

    def test_node_memory_pressure(self):
        c = self._collector([_make_node(conditions={"MemoryPressure": True})])
        metrics, errors = c.collect()

        assert errors == 0
        assert _sample(metrics, "kube_sentinel_node_condition",
                       {"node": "node1", "condition": "MemoryPressure"}) == 1.0
        assert _sample(metrics, "kube_sentinel_node_condition",
                       {"node": "node1", "condition": "DiskPressure"}) == 0.0

    def test_node_not_ready(self):
        c = self._collector([_make_node(ready=False)])
        metrics, errors = c.collect()

        assert errors == 0
        assert _sample(metrics, "kube_sentinel_node_ready", {"node": "node1"}) == 0.0

    def test_requested_resources_summed_from_pods(self):
        spec_container = MagicMock()
        spec_container.resources.requests = {"cpu": "500m", "memory": "256Mi"}
        pod = _make_pod(node_name="node1", spec_containers=[spec_container])
        pod.status.phase = "Running"
        c = self._collector([_make_node()], pods=[pod])
        metrics, errors = c.collect()

        assert errors == 0
        assert _sample(metrics, "kube_sentinel_node_requested_cpu_cores",
                       {"node": "node1"}) == pytest.approx(0.5)
        assert _sample(metrics, "kube_sentinel_node_requested_memory_bytes",
                       {"node": "node1"}) == 256 * 1024**2

    def test_terminal_pods_excluded_from_requested(self):
        spec_container = MagicMock()
        spec_container.resources.requests = {"cpu": "1", "memory": "1Gi"}
        pod = _make_pod(node_name="node1", spec_containers=[spec_container])
        pod.status.phase = "Succeeded"
        c = self._collector([_make_node()], pods=[pod])
        metrics, errors = c.collect()

        assert errors == 0
        assert _sample(metrics, "kube_sentinel_node_requested_cpu_cores",
                       {"node": "node1"}) == 0.0

    def test_api_error_returns_error_count(self):
        v1 = MagicMock()
        v1.list_node.side_effect = ApiException(status=403)
        c = NodeCollector(v1)
        metrics, errors = c.collect()

        assert errors == 1
        assert metrics == []


# ---------------------------------------------------------------------------
# DeploymentCollector — offline
# ---------------------------------------------------------------------------

class TestDeploymentCollectorOffline:
    def _collector(self, *deploys):
        apps_v1 = MagicMock()
        apps_v1.list_deployment_for_all_namespaces.return_value = _deploy_list(*deploys)
        return DeploymentCollector(apps_v1)

    def test_healthy_deployment(self):
        c = self._collector(_make_deployment(desired=3, available=3, ready=3, unavailable=0))
        metrics, errors = c.collect()

        assert errors == 0
        assert _sample(metrics, "kube_sentinel_deployment_replicas_desired",
                       {"namespace": "default", "deployment": "test-deploy"}) == 3.0
        assert _sample(metrics, "kube_sentinel_deployment_replicas_available",
                       {"namespace": "default", "deployment": "test-deploy"}) == 3.0
        assert _sample(metrics, "kube_sentinel_deployment_replicas_ready",
                       {"namespace": "default", "deployment": "test-deploy"}) == 3.0
        assert _sample(metrics, "kube_sentinel_deployment_replicas_unavailable",
                       {"namespace": "default", "deployment": "test-deploy"}) == 0.0

    def test_degraded_deployment(self):
        c = self._collector(_make_deployment(desired=3, available=1, ready=1, unavailable=2))
        metrics, errors = c.collect()

        assert errors == 0
        assert _sample(metrics, "kube_sentinel_deployment_replicas_unavailable",
                       {"namespace": "default", "deployment": "test-deploy"}) == 2.0
        assert _sample(metrics, "kube_sentinel_deployment_replicas_ready",
                       {"namespace": "default", "deployment": "test-deploy"}) == 1.0

    def test_api_error_returns_error_count(self):
        apps_v1 = MagicMock()
        apps_v1.list_deployment_for_all_namespaces.side_effect = ApiException(status=403)
        c = DeploymentCollector(apps_v1)
        metrics, errors = c.collect()

        assert errors == 1
        assert metrics == []


# ---------------------------------------------------------------------------
# Live K8s tests — require minikube (@pytest.mark.k8s)
# ---------------------------------------------------------------------------

@pytest.mark.k8s
def test_live_crashloop_metrics(k8s_clients, test_namespace):
    """Deploy a pod that exits immediately and confirm restart/CrashLoopBackOff metrics."""
    from kubernetes import client as k8s

    v1, _ = k8s_clients
    pod_name = "crashloop-test"

    pod_manifest = k8s.V1Pod(
        metadata=k8s.V1ObjectMeta(name=pod_name, namespace=test_namespace),
        spec=k8s.V1PodSpec(
            restart_policy="Always",
            containers=[
                k8s.V1Container(
                    name="crash-container",
                    image="busybox:1.36",
                    command=["sh", "-c", "exit 1"],
                )
            ],
        ),
    )
    v1.create_namespaced_pod(namespace=test_namespace, body=pod_manifest)

    try:
        # Wait until the container has restarted at least twice (proves crash-loop)
        def _has_restarted():
            pod = v1.read_namespaced_pod(pod_name, test_namespace)
            statuses = pod.status.container_statuses or []
            return statuses and statuses[0].restart_count >= 2

        wait_for(_has_restarted, timeout=180, description="pod restart count >= 2")

        collector = PodCollector(v1)
        metrics, errors = collector.collect()

        assert errors == 0, "Unexpected API error during live scrape"

        restart_val = _sample(
            metrics,
            "kube_sentinel_pod_restart_count",
            {"namespace": test_namespace, "pod": pod_name, "container": "crash-container"},
        )
        assert restart_val is not None and restart_val >= 2, (
            f"Expected restart_count >= 2, got {restart_val}"
        )

        # Assertion 2: CrashLoopBackOff state — separate wait with longer timeout.
        # K8s applies exponential backoff between restarts; CrashLoopBackOff label
        # can take up to 5 min to appear. This is expected behavior, not a slow test.
        def _crashloop_state():
            m2, _ = PodCollector(v1).collect()
            return _sample(
                m2,
                "kube_sentinel_pod_container_state",
                {
                    "namespace": test_namespace,
                    "pod": pod_name,
                    "container": "crash-container",
                    "state": "waiting",
                    "reason": "CrashLoopBackOff",
                },
            ) == 1.0

        wait_for(_crashloop_state, timeout=300, description="CrashLoopBackOff state")

        final_metrics, final_errors = PodCollector(v1).collect()
        assert final_errors == 0
        assert _sample(
            final_metrics,
            "kube_sentinel_pod_container_state",
            {
                "namespace": test_namespace,
                "pod": pod_name,
                "container": "crash-container",
                "state": "waiting",
                "reason": "CrashLoopBackOff",
            },
        ) == 1.0, "CrashLoopBackOff state not present in final scrape"

    finally:
        v1.delete_namespaced_pod(pod_name, test_namespace)


@pytest.mark.k8s
def test_live_unavailable_replicas(k8s_clients, test_namespace):
    """Deploy a deployment with a non-existent image and confirm unavailable replica metric."""
    from kubernetes import client as k8s

    _, apps_v1 = k8s_clients
    deploy_name = "unavailable-test"

    deploy_manifest = k8s.V1Deployment(
        metadata=k8s.V1ObjectMeta(name=deploy_name, namespace=test_namespace),
        spec=k8s.V1DeploymentSpec(
            replicas=2,
            selector=k8s.V1LabelSelector(
                match_labels={"app": deploy_name}
            ),
            template=k8s.V1PodTemplateSpec(
                metadata=k8s.V1ObjectMeta(labels={"app": deploy_name}),
                spec=k8s.V1PodSpec(
                    containers=[
                        k8s.V1Container(
                            name="app",
                            image="this-image-does-not-exist:v0.0.0",
                        )
                    ]
                ),
            ),
        ),
    )
    apps_v1.create_namespaced_deployment(namespace=test_namespace, body=deploy_manifest)

    try:
        # Deployment is immediately unavailable (image can't be pulled)
        def _has_unavailable():
            collector = DeploymentCollector(apps_v1)
            metrics, _ = collector.collect()
            val = _sample(
                metrics,
                "kube_sentinel_deployment_replicas_unavailable",
                {"namespace": test_namespace, "deployment": deploy_name},
            )
            return val is not None and val > 0

        wait_for(_has_unavailable, timeout=60, description="unavailable replicas > 0")

        collector = DeploymentCollector(apps_v1)
        metrics, errors = collector.collect()

        assert errors == 0
        desired = _sample(
            metrics,
            "kube_sentinel_deployment_replicas_desired",
            {"namespace": test_namespace, "deployment": deploy_name},
        )
        unavail = _sample(
            metrics,
            "kube_sentinel_deployment_replicas_unavailable",
            {"namespace": test_namespace, "deployment": deploy_name},
        )
        assert desired == 2.0
        assert unavail is not None and unavail > 0, (
            f"Expected unavailable > 0, got {unavail}"
        )

    finally:
        apps_v1.delete_namespaced_deployment(deploy_name, test_namespace)
