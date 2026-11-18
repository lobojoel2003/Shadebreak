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
| Build number | Number of commits on `main` (`git rev-list --count HEAD`): always increasing, and the same for a commit in CI and in its release | `build 42` |
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
| `:build-42` | Every published build (the commit count) |
| `:edge`, `:sha-abc1234` | Every push to `main` that passes CI |

## Cutting a release

Releases are continuous: when `main` carries a version that has no tag yet,
the **Release** workflow tags it and publishes it.

1. Make sure `CHANGELOG.md` has the changes under `## [Unreleased]`.
2. Bump the version and date the changelog:

   ```bash
   python scripts/release.py bump 1.1.0
   ```

3. Commit and push (or merge a pull request) to `main`:

   ```bash
   git commit -am "Release 1.1.0" && git push origin main
   ```

The **Release** workflow then checks the version against the changelog, runs
the full CI, creates the annotated tag `v1.1.0` with the changelog section as
its message, builds the wheel and sdist, renders the sample heat plans,
publishes the Docker images and creates the GitHub release with these assets:

* `shadebreak-X.Y.Z-py3-none-any.whl` and `shadebreak-X.Y.Z.tar.gz`
* `shadebreak-sample-heat-plan-en.pdf` and `shadebreak-sample-heat-plan-es.pdf`
* `SHA256SUMS.txt`

Pushes to `main` that do not change the version do nothing here (CI still
publishes the `edge` image). You can also push a tag yourself
(`git tag -a v1.1.0 -m "Shadebreak 1.1.0" && git push origin v1.1.0`); it must
match `__version__`. Versions with a suffix (`1.1.0-rc.1`) are published as
pre-releases and do not move `latest`.
