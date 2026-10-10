"""Build version, overridable via IRIS_VERSION at image build time."""

import os

VERSION = os.environ.get("IRIS_VERSION", "2026.10.0-beta.54")
