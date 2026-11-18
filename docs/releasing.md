# Versions, builds and releases

## Version numbers

Shadebreak follows [Semantic Versioning](https://semver.org): `MAJOR.MINOR.PATCH`.

* **PATCH** (1.0.1): fixes that change no behavior a crew relies on.
* **MINOR** (1.1.0): new features; existing plans keep working.
* **MAJOR** (2.0.0): changes that need action when upgrading, or that change
  how breaks, ramps or risk levels are calculated.

The single source of truth is `__version__` in `shadebreak/__init__.py`.
`pyproject.toml` reads it, and the app shows it in every page footer, the heat
plan PDF, `/version` and `/healthz`.

## Build numbers

Every CI run stamps the Docker image with:

| Value | Source | Shown as |
| --- | --- | --- |
| Build number | GitHub Actions run number | `build 42` |
| Commit | Git SHA | `abc1234` |
| Build date | Commit timestamp | `/version` → `date` |

They are baked into the image as `SHADEBREAK_BUILD_NUMBER`,
`SHADEBREAK_GIT_SHA` and `SHADEBREAK_BUILD_DATE`, and into the OCI labels
(`org.opencontainers.image.version`, `.revision`, `.created`,
`io.shadebreak.build-number`). A local checkout shows `build dev`.

## Images

| Tag | Published when |
| --- | --- |
| `ghcr.io/lobojoel2003/shadebreak:1.2.3` | Release `v1.2.3` |
| `:1.2`, `:1` | Latest release in that line |
| `:latest` | Latest stable release |
| `:build-42` | Every published build |
| `:edge`, `:sha-abc1234` | Every push to `main` that passes CI |

## Cutting a release

1. Make sure `main` is green and `CHANGELOG.md` has the changes under
   `## [Unreleased]`.
2. Bump the version and date the changelog:

   ```bash
   python scripts/release.py bump 1.1.0
   ```

3. Commit, tag and push:

   ```bash
   git commit -am "Release 1.1.0"
   ```

   ```bash
   git tag -a v1.1.0 -m "Shadebreak 1.1.0"
   ```

   ```bash
   git push origin main v1.1.0
   ```

The **Release** workflow then checks the tag matches `__version__` and the
changelog, runs the full CI, builds the wheel and sdist, renders the sample
heat plans, publishes the Docker images and creates the GitHub release with
the changelog section as its notes and these assets:

* `shadebreak-X.Y.Z-py3-none-any.whl` and `shadebreak-X.Y.Z.tar.gz`
* `shadebreak-sample-heat-plan-en.pdf` and `shadebreak-sample-heat-plan-es.pdf`
* `SHA256SUMS.txt`

Tags with a suffix (`v1.1.0-rc.1`) are published as pre-releases and do not
move `latest`.
