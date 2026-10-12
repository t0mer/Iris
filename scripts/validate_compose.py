"""Validate deployment examples with Docker Compose; never start containers."""

import os
import re
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
files = [root / "docker-compose.example.yml", *sorted((root / "docker-compose").rglob("*.yml"))]
for path in files:
    source = path.read_text()
    if not re.search(r"^services:", source, re.MULTILINE):
        continue
    env = dict(os.environ)
    for name in re.findall(r"\$\{([A-Z0-9_]+)", source):
        if name.endswith("_IMAGE"):
            env[name] = "example/validated:1"
        elif name.endswith("_PATH"):
            env[name] = "/tmp/iris-compose-validation"
        elif name.endswith("_URL"):
            env[name] = "https://iris.example.com"
        elif name in {
            "IRIS_SECRET_KEY",
            "IRIS_ADMIN_PASSWORD",
            "IRIS_METRICS_TOKEN",
            "OPENWA_API_KEY_PEPPER",
            "DB_PASSWORD",
        }:
            env[name] = "compose-validation-only"
    subprocess.run(["docker", "compose", "-f", str(path), "config", "--quiet"], env=env, check=True)
    print(f"Validated {path.relative_to(root)}")
