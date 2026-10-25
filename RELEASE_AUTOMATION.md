# Dependency updates and verified releases

Dependabot checks the backend (`uv.lock`), frontend (`package-lock.json`),
GitHub Actions, Docker base images, native transcription companion packages
and isolated training requirements every
Monday. Compatible minor/patch updates are grouped; major application updates
remain separate PRs. Updates are reviewed through pull requests, not automatically
merged. This uses [GitHub's supported ecosystems](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories)
and [uv's Dependabot integration](https://docs.astral.sh/uv/guides/integration/dependabot/).
The configuration becomes active after it reaches the repository's default branch.

Every update PR runs the ordinary CI workflow: Python lint/type checks and backend
tests on SQLite, PostgreSQL and MySQL; frontend lint, format, translations, tests
and production build; deployment validation; security scanning; amd64 container
startup and health checks; and amd64/arm64 builds. Backend lock consistency is
checked before installation. The isolated CPU training job tests actual adapter
weight changes and generated-output evaluation using synthetic examples only.
The random demonstration adapter is not published or installed into Iris.
CI also runs weekly on Tuesday and can be started manually. This checks the
implemented dependency versions; Dependabot opens the proposed upgrade PRs.

## Release a version

After merging a tested commit into `main`, push a tag such as `2026.10.1`
or `v2026.10.1`. Prereleases use `2026.10.1-beta.1`, `-alpha.1` or `-rc.1`.
Tag validation rejects malformed versions and commits outside `main` history.
The Release workflow runs the complete reusable CI and native transcription
companion tests against the tagged commit. Publishing waits for both workflows
to succeed. A failed check prevents publishing.

Successful releases publish a multiarchitecture image with the tag's version
embedded in the app, image provenance and SBOM, then create a GitHub release
with generated notes and the image digest. Stable versions update `latest`;
prereleases do not. Manual releases remain available on `main`, with an optional
version or the next monthly patch number; the tag is created after image upload.

Repository administrators must configure `DOCKERHUB_USERNAME` and
`DOCKERHUB_TOKEN` Actions secrets with push access. `DOCKERHUB_IMAGE` is an optional
repository variable (default `techblog/iris`). GitHub releases use the workflow's
scoped token. Forks should set their own image variable and credentials.
Enable branch protection/rulesets to require CI before merging upgrade PRs.
Workflow configuration cannot itself enforce repository merge policies.

No production stack is automatically deployed by release publication. Existing
local settings, models and private data are unaffected by this automation.
