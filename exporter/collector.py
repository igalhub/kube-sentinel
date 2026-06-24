import logging
from kubernetes import client as k8s
from kubernetes.client.exceptions import ApiException
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily

logger = logging.getLogger(__name__)

_POD_PHASES = ("Pending", "Running", "Succeeded", "Failed", "Unknown")
_NODE_PRESSURE_CONDITIONS = ("MemoryPressure", "DiskPressure", "PIDPressure")


def _parse_cpu(quantity: str) -> float:
    if not quantity:
        return 0.0
    if quantity.endswith("m"):
        return float(quantity[:-1]) / 1000.0
    return float(quantity)


def _parse_memory(quantity: str) -> float:
    if not quantity:
        return 0.0
    # Longest suffix first to avoid partial matches (e.g. 'M' vs 'Mi')
    for suffix, factor in (
        ("Ki", 1024), ("Mi", 1024**2), ("Gi", 1024**3), ("Ti", 1024**4),
        ("Pi", 1024**5), ("Ei", 1024**6),
        ("K", 1000), ("M", 1000**2), ("G", 1000**3), ("T", 1000**4),
        ("P", 1000**5), ("E", 1000**6),
    ):
        if quantity.endswith(suffix):
            return float(quantity[: -len(suffix)]) * factor
    return float(quantity)


class PodCollector:
    def __init__(self, v1: k8s.CoreV1Api, namespaces=None):
        self._v1 = v1
        self._namespaces = set(namespaces) if namespaces else set()

    def collect(self):
        """Return (list[Metric], error_count)."""
        restart_count = GaugeMetricFamily(
            "kube_sentinel_pod_restart_count",
            "Total restart count for a container",
            labels=["namespace", "pod", "container"],
        )
        pod_ready = GaugeMetricFamily(
            "kube_sentinel_pod_ready",
            "1 if the pod passes its Ready condition, 0 otherwise",
            labels=["namespace", "pod"],
        )
        pod_phase = GaugeMetricFamily(
            "kube_sentinel_pod_phase",
            "1 if the pod is in this phase, 0 otherwise",
            labels=["namespace", "pod", "phase"],
        )
        container_state = GaugeMetricFamily(
            "kube_sentinel_pod_container_state",
            "1 if the container is in this state/reason combination",
            labels=["namespace", "pod", "container", "state", "reason"],
        )

        try:
            pods = self._v1.list_pod_for_all_namespaces()
        except ApiException as e:
            logger.error("PodCollector API error: %s", e)
            return [], 1

        for pod in pods.items:
            ns = pod.metadata.namespace
            name = pod.metadata.name

            if self._namespaces and ns not in self._namespaces:
                continue

            phase = (pod.status.phase or "Unknown") if pod.status else "Unknown"
            for p in _POD_PHASES:
                pod_phase.add_metric([ns, name, p], 1.0 if phase == p else 0.0)

            ready = 0.0
            if pod.status and pod.status.conditions:
                for cond in pod.status.conditions:
                    if cond.type == "Ready":
                        ready = 1.0 if cond.status == "True" else 0.0
                        break
            pod_ready.add_metric([ns, name], ready)

            if pod.status and pod.status.container_statuses:
                for cs in pod.status.container_statuses:
                    restart_count.add_metric(
                        [ns, name, cs.name], float(cs.restart_count or 0)
                    )
                    state = cs.state
                    if state.running is not None:
                        container_state.add_metric(
                            [ns, name, cs.name, "running", ""], 1.0
                        )
                    elif state.waiting is not None:
                        reason = (state.waiting.reason or "") if state.waiting else ""
                        container_state.add_metric(
                            [ns, name, cs.name, "waiting", reason], 1.0
                        )
                    elif state.terminated is not None:
                        reason = (
                            (state.terminated.reason or "") if state.terminated else ""
                        )
                        container_state.add_metric(
                            [ns, name, cs.name, "terminated", reason], 1.0
                        )

        return [restart_count, pod_ready, pod_phase, container_state], 0


class NodeCollector:
    def __init__(self, v1: k8s.CoreV1Api):
        self._v1 = v1

    def collect(self):
        """Return (list[Metric], error_count)."""
        node_ready = GaugeMetricFamily(
            "kube_sentinel_node_ready",
            "1 if the node is ready, 0 otherwise",
            labels=["node"],
        )
        node_condition = GaugeMetricFamily(
            "kube_sentinel_node_condition",
            "1 if the node condition is active",
            labels=["node", "condition"],
        )
        allocatable_cpu = GaugeMetricFamily(
            "kube_sentinel_node_allocatable_cpu_cores",
            "Allocatable CPU in cores",
            labels=["node"],
        )
        allocatable_mem = GaugeMetricFamily(
            "kube_sentinel_node_allocatable_memory_bytes",
            "Allocatable memory in bytes",
            labels=["node"],
        )
        requested_cpu = GaugeMetricFamily(
            "kube_sentinel_node_requested_cpu_cores",
            "Total CPU requested by running pods on this node, in cores",
            labels=["node"],
        )
        requested_mem = GaugeMetricFamily(
            "kube_sentinel_node_requested_memory_bytes",
            "Total memory requested by running pods on this node, in bytes",
            labels=["node"],
        )

        try:
            nodes = self._v1.list_node()
            pods = self._v1.list_pod_for_all_namespaces()
        except ApiException as e:
            logger.error("NodeCollector API error: %s", e)
            return [], 1

        # Sum resource requests per node from non-terminal pods
        cpu_req: dict[str, float] = {}
        mem_req: dict[str, float] = {}
        for pod in pods.items:
            node_name = pod.spec.node_name if pod.spec else None
            if not node_name:
                continue
            if pod.status and pod.status.phase in ("Succeeded", "Failed"):
                continue
            cpu_req.setdefault(node_name, 0.0)
            mem_req.setdefault(node_name, 0.0)
            for container in (pod.spec.containers or []):
                reqs = (
                    container.resources.requests
                    if container.resources and container.resources.requests
                    else {}
                )
                if "cpu" in reqs:
                    cpu_req[node_name] += _parse_cpu(reqs["cpu"])
                if "memory" in reqs:
                    mem_req[node_name] += _parse_memory(reqs["memory"])

        for node in nodes.items:
            name = node.metadata.name
            alloc = (node.status.allocatable or {}) if node.status else {}

            allocatable_cpu.add_metric([name], _parse_cpu(alloc.get("cpu", "0")))
            allocatable_mem.add_metric([name], _parse_memory(alloc.get("memory", "0")))
            requested_cpu.add_metric([name], cpu_req.get(name, 0.0))
            requested_mem.add_metric([name], mem_req.get(name, 0.0))

            ready_val = 0.0
            pressure_vals: dict[str, float] = {c: 0.0 for c in _NODE_PRESSURE_CONDITIONS}
            if node.status and node.status.conditions:
                for cond in node.status.conditions:
                    if cond.type == "Ready":
                        ready_val = 1.0 if cond.status == "True" else 0.0
                    if cond.type in _NODE_PRESSURE_CONDITIONS:
                        pressure_vals[cond.type] = (
                            1.0 if cond.status == "True" else 0.0
                        )
            node_ready.add_metric([name], ready_val)
            for cond_name, val in pressure_vals.items():
                node_condition.add_metric([name, cond_name], val)

        return [
            node_ready, node_condition,
            allocatable_cpu, allocatable_mem,
            requested_cpu, requested_mem,
        ], 0


class DeploymentCollector:
    def __init__(self, apps_v1: k8s.AppsV1Api, namespaces=None):
        self._apps_v1 = apps_v1
        self._namespaces = set(namespaces) if namespaces else set()

    def collect(self):
        """Return (list[Metric], error_count)."""
        desired = GaugeMetricFamily(
            "kube_sentinel_deployment_replicas_desired",
            "Desired number of replicas",
            labels=["namespace", "deployment"],
        )
        available = GaugeMetricFamily(
            "kube_sentinel_deployment_replicas_available",
            "Available replicas",
            labels=["namespace", "deployment"],
        )
        ready = GaugeMetricFamily(
            "kube_sentinel_deployment_replicas_ready",
            "Ready replicas",
            labels=["namespace", "deployment"],
        )
        unavailable = GaugeMetricFamily(
            "kube_sentinel_deployment_replicas_unavailable",
            "Unavailable replicas",
            labels=["namespace", "deployment"],
        )

        try:
            deployments = self._apps_v1.list_deployment_for_all_namespaces()
        except ApiException as e:
            logger.error("DeploymentCollector API error: %s", e)
            return [], 1

        for deploy in deployments.items:
            ns = deploy.metadata.namespace
            name = deploy.metadata.name
            desired.add_metric([ns, name], float(deploy.spec.replicas or 0))
            available.add_metric(
                [ns, name], float(deploy.status.available_replicas or 0)
            )
            ready.add_metric([ns, name], float(deploy.status.ready_replicas or 0))
            unavailable.add_metric(
                [ns, name], float(deploy.status.unavailable_replicas or 0)
            )

        return [desired, available, ready, unavailable], 0
