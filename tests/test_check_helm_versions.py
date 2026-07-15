import textwrap

from scripts.check_helm_versions import find_helm_releases


def _write_tf(tmp_path, content):
    tf_path = tmp_path / "main.tf"
    tf_path.write_text(textwrap.dedent(content))
    return str(tf_path)


class TestFindHelmReleases:
    def test_registry_chart_with_version_has_no_violation(self, tmp_path):
        tf_path = _write_tf(
            tmp_path,
            """
            resource "helm_release" "prometheus" {
              repository = "https://prometheus-community.github.io/helm-charts"
              chart      = "prometheus"
              version    = "29.13.0"
            }
            """,
        )
        [(name, attrs)] = find_helm_releases(tf_path)
        assert name == "prometheus"
        assert "repository" in attrs and "version" in attrs

    def test_registry_chart_without_version_is_a_violation(self, tmp_path):
        tf_path = _write_tf(
            tmp_path,
            """
            resource "helm_release" "prometheus" {
              repository = "https://prometheus-community.github.io/helm-charts"
              chart      = "prometheus"
            }
            """,
        )
        [(name, attrs)] = find_helm_releases(tf_path)
        assert name == "prometheus"
        assert "repository" in attrs and "version" not in attrs

    def test_local_chart_with_no_repository_is_exempt(self, tmp_path):
        tf_path = _write_tf(
            tmp_path,
            """
            resource "helm_release" "kube_sentinel" {
              chart = "${path.module}/../helm"
            }
            """,
        )
        [(name, attrs)] = find_helm_releases(tf_path)
        assert name == "kube_sentinel"
        assert "repository" not in attrs

    def test_non_helm_release_resources_are_ignored(self, tmp_path):
        tf_path = _write_tf(
            tmp_path,
            """
            resource "kubernetes_namespace" "monitoring" {
              metadata {
                name = "monitoring"
              }
            }
            """,
        )
        assert find_helm_releases(tf_path) == []
