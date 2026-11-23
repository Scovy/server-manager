"""Identify the backend's actual Docker mounts in containerized installations."""

import os
import socket
from typing import Any

from docker.errors import DockerException


def backend_container(client: Any) -> Any:
    try:
        return client.containers.get(socket.gethostname())
    except DockerException as exc:
        raise ValueError("Cannot identify the backend container's mounts") from exc


def panel_data_volume(client: Any) -> str | None:
    destination = os.getenv("HOMELAB_DATA_MOUNT")
    if destination:
        for mount in backend_container(client).attrs["Mounts"]:
            if mount["Destination"] == destination and mount["Type"] == "volume":
                return str(mount["Name"])
    return None
