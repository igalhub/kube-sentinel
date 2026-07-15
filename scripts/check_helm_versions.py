#!/usr/bin/env python3
"""Fail if any registry-based helm_release in terraform/**/*.tf lacks a pinned version.

A helm_release with a "repository" attribute pulls from a chart registry and
must pin "version" explicitly, or a chart upgrade can silently change what
gets deployed (see ba6c9bb). A helm_release with no "repository" (a local
chart path, e.g. helm_release.kube_sentinel) has no registry version to pin
and is correctly exempt.
"""
import glob
import sys

import hcl2


def find_helm_releases(tf_path):
    with open(tf_path) as f:
        parsed = hcl2.load(f)
    releases = []
    for resource_block in parsed.get("resource", []):
        for resource_type, instances in resource_block.items():
            if resource_type.strip('"') != "helm_release":
                continue
            for resource_name, attrs in instances.items():
                releases.append((resource_name.strip('"'), attrs))
    return releases


def main():
    violations = []
    for tf_path in sorted(glob.glob("terraform/**/*.tf", recursive=True)):
        for name, attrs in find_helm_releases(tf_path):
            if "repository" in attrs and "version" not in attrs:
                violations.append(f"{tf_path}: helm_release.{name} has a repository but no version pinned")

    if violations:
        for v in violations:
            print(v)
        return 1

    print("OK: all registry-based helm_release blocks have a pinned version")
    return 0


if __name__ == "__main__":
    sys.exit(main())
