from typing import Any

from app.resources import container_resources


def test_v2_container_memory_and_cpu_limits(tmp_path: Any, monkeypatch: Any) -> None:
    (tmp_path / "memory.current").write_text("680")
    (tmp_path / "memory.max").write_text("1000")
    (tmp_path / "cpu.max").write_text("200000 100000")
    counters = iter((1.0, 1.25))
    clocks = iter((10.0, 10.25))
    monkeypatch.setattr("app.resources._cpu_seconds", lambda root: next(counters))
    monkeypatch.setattr("app.resources.time.monotonic", lambda: next(clocks))
    monkeypatch.setattr("app.resources.time.sleep", lambda duration: None)
    monkeypatch.setattr("app.resources.os.cpu_count", lambda: 4)
    if hasattr(__import__("os"), "sched_getaffinity"):
        monkeypatch.setattr("app.resources.os.sched_getaffinity", lambda pid: {0, 1, 2, 3})
    result = container_resources(tmp_path)
    assert result["memory"] == {"used_bytes": 680, "total_bytes": 1000, "free_bytes": 320}
    assert result["cpu"]["cores"] == 2
    assert result["cpu"]["usage_percentage"] == 50


def test_unavailable_and_unlimited_memory_stay_unknown(tmp_path: Any) -> None:
    assert container_resources(tmp_path)["memory"]["total_bytes"] is None
    (tmp_path / "memory.current").write_text("100")
    (tmp_path / "memory.max").write_text("max")
    assert container_resources(tmp_path)["memory"]["total_bytes"] is None


def test_v1_container_counters(tmp_path: Any, monkeypatch: Any) -> None:
    for folder in ("memory", "cpu", "cpuacct"):
        (tmp_path / folder).mkdir()
    for name, value in {
        "memory/memory.usage_in_bytes": "512",
        "memory/memory.limit_in_bytes": "1024",
        "cpu/cpu.cfs_quota_us": "100000",
        "cpu/cpu.cfs_period_us": "100000",
        "cpuacct/cpuacct.usage": "1000000000",
    }.items():
        (tmp_path / name).write_text(value)
    clocks = iter((10.0, 10.25))
    monkeypatch.setattr("app.resources.time.monotonic", lambda: next(clocks))
    monkeypatch.setattr("app.resources.time.sleep", lambda duration: None)
    result = container_resources(tmp_path)
    assert result["memory"]["total_bytes"] == 1024
    assert result["cpu"]["usage_percentage"] == 0
    assert result["cpu"]["cores"] == 1


def test_old_kernel_without_cpu_quota_still_reports_usage(tmp_path: Any, monkeypatch: Any) -> None:
    (tmp_path / "cpuacct").mkdir()
    (tmp_path / "cpuacct/cpuacct.usage").write_text("1000000000")
    clocks = iter((10.0, 10.25))
    monkeypatch.setattr("app.resources.time.monotonic", lambda: next(clocks))
    monkeypatch.setattr("app.resources.time.sleep", lambda duration: None)
    result = container_resources(tmp_path)
    assert result["cpu"]["usage_percentage"] == 0
    assert result["cpu"]["cores"] > 0
