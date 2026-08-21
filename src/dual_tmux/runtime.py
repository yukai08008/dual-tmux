from __future__ import annotations


def build_cmd(host: str, container: str, directory: str) -> str:
    if container:
        inner = f"cd {directory} && exec bash"
        return f"ssh -t {host} \"docker exec -it {container} bash -lc '{inner}'\""
    if directory and directory != "/workspace":
        return f"ssh -t {host} \"cd {directory} && exec bash\""
    return f"ssh -t {host}"
