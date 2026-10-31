# Parseus Development Guide

This guide covers local development with the repository `Makefile`.

## Requirements

- Python 3.11 - 3.13 (the application source requires this range; this is separate from the Python 3.8+ needed only to run `manage_parseus.py` when deploying, see [MANAGEMENT.md](MANAGEMENT.md))
- GNU Make
- Node.js 20 or later and npm (the JavaScript tests use Node's built-in test runner, which needs Node 18+)
- Docker and Docker Compose v2, recommended for Redis and Elasticsearch
- OpenSSL

## One-time setup

From the repository root:

    make setup

This will:

- create a virtual environment at `.venv`
- install Python dependencies in editable development mode
- install and build frontend assets with npm
- run Django `collectstatic` and `compress`
- create `envs/development.env` with generated Django and Fernet keys
- apply migrations and create scheduled tasks

## Start development dependencies

Start Redis:

    make start-redis

Start Elasticsearch:

    make start-elasticsearch

By default, `envs/development.env` expects Redis at `redis://localhost:6379/0` and Elasticsearch at `http://127.0.0.1:9200`.

## Run Parseus locally

Run the webserver, Celery beat, and Celery worker together:

    make run

Run only the webserver:

    make run-web

Run only Celery beat and worker:

    make run-celery

When the webserver is running, open:

    http://localhost:8080/

All `make run*` targets run in the foreground. Press Ctrl+C to stop them.

## Run the tests

Run every test suite (Python, then JavaScript):

    make tests

Or one at a time:

    make test-python
    make test-js

Pass extra pytest arguments with `PYTEST_ARGS`, for example `make test-python PYTEST_ARGS="-k alerts"`.

Python tests live in two places and both are collected by `pytest`:

- `tests/` for cross-cutting tests
- next to the app they test, for example `src/parseus/webapp/alerts/tests.py`

Some tests in `tests/` use a real datastore at `DATASTORE_HOST_URL` (default `http://localhost:9200`), so run
`make start-elasticsearch` first.

Browser-script tests use Node's built-in test runner with jsdom (a dev dependency installed by `npm install`).
They load the real script into a simulated page, so they need no browser and no running server. They live next to
the script, for example `src/parseus/webapp/alerts/js_tests/`.

## Cleanup

Remove generated development/build artifacts:

    make clean

## Packaging

Create a deployable bundle:

    make package

The package target stages required runtime files and Docker image archives under `dist/`.
It reads the release version from `pyproject.toml` and writes a bundle named
`dist/parseus-<version>.tar.gz`, with staged contents under `dist/parseus-<version>/`.

## Versioning and release workflow

Parseus uses `pyproject.toml` `[project].version` as the source of truth for the application release version. Do not hardcode release versions in packaging scripts, Compose files, Docker labels, or documentation examples when `parseus-<version>` can be used instead.

Release versions should follow Semantic Versioning (`MAJOR.MINOR.PATCH`):

- increment `MAJOR` for incompatible changes
- increment `MINOR` for backward-compatible feature additions
- increment `PATCH` for backward-compatible bug fixes or documentation-only release corrections

Release tags must use the format `vX.Y.Z`, for example `v1.2.3`. The tag's numeric part must exactly match `[project].version` in `pyproject.toml`.

Before creating a release tag:

1. Update `pyproject.toml` `[project].version` to the intended SemVer value.
2. Update release notes or changelog material, if present for the release.
3. Build the release package:

       make package

4. Confirm the generated archive path uses the intended version, for example `dist/parseus-<version>.tar.gz`.
5. Commit the version and documentation changes.
6. Create and push the matching tag:

       git tag v<version>
       git push <remote> v<version>

GitLab CI performs release validation for tag pipelines:

- `verify-version` strips the leading `v` from `CI_COMMIT_TAG` and compares it to `pyproject.toml` `[project].version`.
- `verify-release-compose` verifies Compose-rendered Parseus images use `parseus:<version>`, rejects hardcoded versioned image references in Compose files, and rejects `parseus:dev` in release image lists.

The Makefile exports `PARSEUS_VERSION` from `pyproject.toml` so Docker image tags, Compose rendering, and package names stay aligned. The management installer records the resolved application version in the installation manifest; `manage-parseus status` prints it as `App version: <version>`.
