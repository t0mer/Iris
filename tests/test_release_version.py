from datetime import date

import pytest

from scripts.release_version import next_version, release_version


@pytest.mark.parametrize("tag", ["2026.10.0", "v2026.10.12", "2026.1.0"])
def test_stable_release(tag):
    assert release_version(tag) == {
        "tag": tag,
        "version": tag.removeprefix("v"),
        "prerelease": "false",
    }


@pytest.mark.parametrize("stage", ["alpha", "beta", "rc"])
def test_prerelease(stage):
    assert release_version(f"v2026.10.0-{stage}.56")["prerelease"] == "true"


@pytest.mark.parametrize(
    "tag",
    ["latest", "2026.13.0", "2026.0.1", "2026.10.01", "2026.10.0-beta.0", "2026.10.0\nX=1"],
)
def test_invalid_release(tag):
    with pytest.raises(ValueError):
        release_version(tag)


def test_next_release_counts_prefixed_tags_and_ignores_beta():
    assert (
        next_version(
            ["2026.10.0", "v2026.10.4", "2026.10.0-beta.56", "2026.9.90", "latest"],
            date(2026, 10, 11),
        )
        == "2026.10.5"
    )


def test_next_release_with_only_prereleases_starts_at_zero():
    assert next_version(["2026.10.0-beta.56"], date(2026, 10, 11)) == "2026.10.0"


def test_next_release_normalizes_single_digit_month():
    assert next_version(["2026.01.3"], date(2026, 1, 11)) == "2026.1.4"
