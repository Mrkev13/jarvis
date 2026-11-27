#!/usr/bin/env python3
"""Read-only guard for the first MRK-108 production deployment."""

import json
import re
import subprocess
import sys
from pathlib import Path

SHARED = Path("/srv/standa-hub/shared")

SERVICES = {
    "backend": {
        "name": "standa-hub-backend",
        "project": "backend",
        "baseline_image": "standa-hub-backend:baseline-mrk108",
        "networks": {"postgres_default", "jarvis_api"},
        "port": ("8000/tcp", "127.0.0.1", "8000"),
        "mounts": {
            ("/srv/standa-hub-data/media", "/data/media"),
            ("/srv/standa-hub-data/backups", "/data/backups"),
        },
    },
    "frontend": {
        "name": "standa-hub-frontend",
        "project": "frontend",
        "baseline_image": "standa-hub-frontend:baseline-mrk108",
        "networks": {"frontend_default", "jarvis_api"},
        "port": ("3000/tcp", "127.0.0.1", "3000"),
        "mounts": set(),
    },
}


def docker_inspect(kind, name):
    result = subprocess.run(
        ["sudo", "docker", kind, "inspect", name],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)[0]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    require(
        len(sys.argv) == 2 and
        re.fullmatch(r"[0-9a-f]{40}", sys.argv[1]) is not None,
        "USAGE: check-production-baseline.py COMMIT_SHA",
    )

    commit = sys.argv[1]
    plan_path = SHARED / f"deployment-plan-{commit}.json"

    plan = json.loads(plan_path.read_text())

    require(plan["target_commit"] == commit, "PLAN_COMMIT_MISMATCH")
    require(plan["status"] == "prepared_only", "PLAN_STATUS_MISMATCH")
    require(
        plan["deployment_enabled"] is False,
        "UNEXPECTED_DEPLOYMENT_ENABLED",
    )

    for service, spec in SERVICES.items():
        previous = plan["previous"][service]
        target = plan["target"][service]

        container = docker_inspect("container", spec["name"])
        baseline_image = docker_inspect("image", spec["baseline_image"])
        target_image = docker_inspect(
            "image", target["image_reference"]
        )

        labels = container["Config"].get("Labels") or {}
        current_image = container["Image"]

        require(
            labels.get("com.docker.compose.project") == spec["project"],
            f"{service}: PROJECT_MISMATCH",
        )
        require(
            previous["name"] == spec["name"],
            f"{service}: CONTAINER_NAME_MISMATCH",
        )
        require(
            previous["container_id"] == container["Id"],
            f"{service}: CONTAINER_CHANGED",
        )
        require(
            current_image == previous["image_id"],
            f"{service}: RUNNING_IMAGE_CHANGED",
        )
        require(
            baseline_image["Id"] == current_image,
            f"{service}: BASELINE_IMAGE_CHANGED",
        )
        require(
            target_image["Id"] == target["image_id"],
            f"{service}: TARGET_IMAGE_CHANGED",
        )
        require(
            target_image["Config"]["Labels"].get(
                "org.opencontainers.image.revision"
            ) == commit,
            f"{service}: TARGET_REVISION_MISMATCH",
        )
        require(
            container["State"]["Running"] is True,
            f"{service}: CONTAINER_NOT_RUNNING",
        )
        require(
            container["HostConfig"]["RestartPolicy"]["Name"]
            == "unless-stopped",
            f"{service}: RESTART_POLICY_MISMATCH",
        )

        networks = set(container["NetworkSettings"]["Networks"])
        require(
            networks == spec["networks"],
            f"{service}: NETWORK_MISMATCH",
        )

        port, host_ip, host_port = spec["port"]
        bindings = container["HostConfig"]["PortBindings"] or {}

        require(
            set(bindings) == {port},
            f"{service}: PORT_MAPPING_CHANGED",
        )
        require(
            bindings[port] == [{
                "HostIp": host_ip,
                "HostPort": host_port,
            }],
            f"{service}: PORT_BINDING_MISMATCH",
        )

        mounts = {
            (m["Source"], m["Destination"])
            for m in container["Mounts"]
            if m["Type"] == "bind"
        }
        require(
            mounts == spec["mounts"],
            f"{service}: BIND_MOUNTS_MISMATCH",
        )

        print(f"{service.upper()}_BASELINE_VERIFIED")

    print("PRODUCTION_BASELINE_VERIFIED")
    print("NO_PRODUCTION_CHANGES")


if __name__ == "__main__":
    try:
        main()
    except (
        RuntimeError, OSError, KeyError, ValueError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"BASELINE_CHECK_FAILED: {error}", file=sys.stderr)
        sys.exit(1)
