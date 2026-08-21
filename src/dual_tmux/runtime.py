from __future__ import annotations

from .sshutil import SshTarget


def build_cmd(host: str, container: str, directory: str, port: int = 22) -> str:
    target = SshTarget(host, port)
    prefix = " ".join(["ssh", "-t", *target.extra_args, target.dest])
    if container:
        inner = f"cd {directory} && exec bash"
        return f"{prefix} \"docker exec -it {container} bash -lc '{inner}'\""
    if directory and directory != "/workspace":
        return f"{prefix} \"cd {directory} && exec bash\""
    return prefix
