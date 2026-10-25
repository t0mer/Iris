#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
git -C "$ROOT" tag --list | python "$ROOT/scripts/release_version.py" --next
