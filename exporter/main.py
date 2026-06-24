import logging
import os
import signal
import threading
import time

from kubernetes import client as k8s
from kubernetes import config as k8s_config
from kubernetes.config.config_exception import ConfigException
from prometheus_client import CollectorRegistry, start_http_server
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

from exporter.collector import DeploymentCollector, NodeCollector, PodCollector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _load_config():
    try:
        k8s_config.load_incluster_config()
        logger.info("Using in-cluster ServiceAccount config")
    except ConfigException:
        k8s_config.load_kube_config()
        logger.info("Using kubeconfig (local development)")


class KubeSentinelCollector:
    """Top-level custom collector registered with Prometheus.

    Delegates to sub-collectors and appends scrape self-metrics.
    """

    def __init__(self, v1: k8s.CoreV1Api, apps_v1: k8s.AppsV1Api, namespaces=None):
        self._sub_collectors = [
            PodCollector(v1, namespaces),
            NodeCollector(v1),
            DeploymentCollector(apps_v1, namespaces),
        ]

    def collect(self):
        start = time.monotonic()
        total_errors = 0

        for sub in self._sub_collectors:
            metrics, errors = sub.collect()
            total_errors += errors
            yield from metrics

        duration = time.monotonic() - start

        d = GaugeMetricFamily(
            "kube_sentinel_scrape_duration_seconds",
            "Time taken for the last scrape of all collectors",
        )
        d.add_metric([], duration)
        yield d

        e = CounterMetricFamily(
            "kube_sentinel_scrape_errors_total",
            "Total K8s API errors encountered across all collectors",
        )
        e.add_metric([], float(total_errors))
        yield e

        up = GaugeMetricFamily(
            "kube_sentinel_up",
            "1 if the last scrape completed without errors",
        )
        up.add_metric([], 0.0 if total_errors else 1.0)
        yield up


def main():
    port = int(os.environ.get("KUBE_SENTINEL_PORT", "8080"))
    namespaces_env = os.environ.get("KUBE_SENTINEL_NAMESPACES", "")
    namespaces = [n.strip() for n in namespaces_env.split(",") if n.strip()]

    _load_config()

    v1 = k8s.CoreV1Api()
    apps_v1 = k8s.AppsV1Api()

    registry = CollectorRegistry()
    registry.register(KubeSentinelCollector(v1, apps_v1, namespaces or None))

    start_http_server(port, registry=registry)
    logger.info("kube-sentinel listening on :%d/metrics", port)

    stop = threading.Event()

    def _shutdown(sig, _frame):
        logger.info("Received signal %s, shutting down", sig)
        stop.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    stop.wait()


if __name__ == "__main__":
    main()
