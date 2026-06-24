"""Live K8s fixtures — only loaded when -m k8s tests run against minikube."""
import time
import pytest
from kubernetes import client as k8s
from kubernetes import config as k8s_config
from kubernetes.client.exceptions import ApiException

TEST_NAMESPACE = "kube-sentinel-test"


@pytest.fixture(scope="session")
def k8s_clients():
    k8s_config.load_kube_config()
    return k8s.CoreV1Api(), k8s.AppsV1Api()


@pytest.fixture(scope="session")
def test_namespace(k8s_clients):
    v1, _ = k8s_clients
    ns = k8s.V1Namespace(metadata=k8s.V1ObjectMeta(name=TEST_NAMESPACE))
    try:
        v1.create_namespace(ns)
    except ApiException as e:
        if e.status != 409:  # 409 = already exists
            raise
    yield TEST_NAMESPACE
    v1.delete_namespace(TEST_NAMESPACE)


def wait_for(condition_fn, timeout=180, interval=5, description="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = condition_fn()
        if result:
            return result
        time.sleep(interval)
    raise TimeoutError(f"Timed out waiting for {description} after {timeout}s")
