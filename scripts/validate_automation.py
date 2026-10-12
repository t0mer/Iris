"""Check dependency automation coverage and required release gates (requires PyYAML)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict:
    # BaseLoader preserves the YAML 1.2 key 'on', unlike PyYAML's YAML 1.1 SafeLoader.
    return yaml.load((ROOT / ".github" / name).read_text(), Loader=yaml.BaseLoader)


def validate() -> None:
    updates = load("dependabot.yml")["updates"]
    expected = {
        ("uv", "/"),
        ("npm", "/web"),
        ("github-actions", "/"),
        ("docker", "/"),
        ("pip", "/scripts"),
        ("pip", "/docker-compose/local/macos"),
    }
    assert {(u["package-ecosystem"], u["directory"]) for u in updates} == expected
    ci = load("workflows/ci.yml")
    assert {"pull_request", "push", "workflow_call", "schedule"} <= ci["on"].keys()
    assert {
        "python",
        "postgres",
        "mysql",
        "web",
        "security",
        "image",
        "compose",
        "learning-training",
        "mcp",
    } <= ci["jobs"].keys()
    assert "workflow_call" in load("workflows/native-transcription.yml")["on"]
    release = load("workflows/docker.yml")
    assert release["on"]["push"]["tags"]
    jobs = release["jobs"]
    assert set(jobs["publish"]["needs"]) == {"version", "verify", "companion"}
    assert jobs["verify"]["uses"] == "./.github/workflows/ci.yml"
    assert jobs["companion"]["uses"] == "./.github/workflows/native-transcription.yml"
    assert jobs["verify"]["needs"] == "version"
    assert "if" not in jobs["publish"]  # Failures must never be bypassed by always().
    print("Dependency coverage and release test gates verified.")


if __name__ == "__main__":
    validate()
