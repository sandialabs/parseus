# Parseus

Parseus is a web application for data analysis and visualization, with support for Modbus data retrieval, model-based analytics, and advanced exploratory analysis.

## Documentation

- [Management guide](docs/MANAGEMENT.md) — install, upgrade, start, stop, restart, uninstall, bundle workflow, requirements, and command reference
- [Development guide](docs/DEVELOPMENT.md) — local development setup, run targets, cleanup, and packaging
- [Troubleshooting guide](docs/TROUBLESHOOTING.md) — common deployment and runtime issues
- [Optional integrations overview](deploy/integrations/README.md) — supported integrations, Compose profiles, and verification helpers
- [GPIB ingestor guide](deploy/integrations/gpib/README.md) — optional GPIB-over-Ethernet ingestion setup, verification, and operations
- [Windows Logstash ingestion guide](deploy/integrations/winlog/README.md) — optional Windows event ingestion pipeline, retention, verification, and operations

## Overview

Parseus provides tools for retrieving, analyzing, and visualizing data from Modbus devices. It supports:

- training analytics models from known-good data
- running predictions using previously trained models
- viewing results as JSON
- retrieving and visualizing register data
- analyzing Modbus function codes
- performing advanced analysis such as HDBSCAN clustering and PCA

## Features

- **Train analytics models** from known-good data
- **Run analytics** using previously trained models
- **View results** as JSON objects
- **Retrieve register values** from Modbus devices
- **Analyze Modbus function codes**
- **Visualize register data** as line graphs
- **Perform advanced analysis** with HDBSCAN clustering and PCA

## Quick Start

On a Linux (x86_64 / AMD64 only) system with Python 3.8 or later (for the management script only), Docker, Docker Compose v2, and OpenSSL installed:

    sudo python3 manage_parseus.py install

When installation completes, open:

    https://127.0.0.1/

Default system-wide layout:

    /opt/parseus                  application files
    /etc/parseus                  configuration, env files, certificates
    /var/lib/parseus              installer state and runtime Compose files
    /srv/parseus/ftp              optional Winlog ingest drop directory
    /var/log/parseus              Parseus host logs
    /usr/local/bin/manage-parseus management command wrapper

To check status, or to stop, start, or uninstall later:

    sudo manage-parseus status
    sudo manage-parseus down
    sudo manage-parseus up
    sudo manage-parseus uninstall

`status`, `up`, `down`, and `restart` can be run with `sudo`, or by a member of the `parseus-admin` group without `sudo`; `install`, `upgrade`, and `uninstall` require root. To optionally run status and runtime commands without `sudo`, add yourself to the `parseus-admin` group:

    sudo usermod -aG parseus-admin "$USER"

Log out and back in for the new group membership to take effect. If `sudo manage-parseus` reports "command not found", your sudo configuration may exclude `/usr/local/bin`; use the full path `sudo /usr/local/bin/manage-parseus <command>` instead.

For full installation, bundle, upgrade, runtime, and uninstall details, see the [management guide](docs/MANAGEMENT.md).

## Requirements Summary

Deployment with `manage_parseus.py` is supported on Linux only.

Parseus has two separate Python requirements:

- **Deploying Parseus** (`manage_parseus.py` / `manage-parseus`, which installs and runs the containers): Python 3.8 or later on the host. The management script is standard-library only. The application itself runs inside the Docker images, so the host does not need the application's Python version.
- **Developing or running the Parseus source code directly** (the `parseus` package under `src/`, tests, `make setup`): Python 3.11 - 3.13, as declared by `requires-python` in `pyproject.toml`.

Minimum deployment hardware:

- 8 CPU cores
- 16 GB RAM
- 20 GB of free disk space

Deployment software:

- Python 3.8 or later (management script only)
- Docker
- Docker Compose v2
- OpenSSL

Development software:

- Python 3.11 - 3.13 (application source code)
- GNU Make
- Node.js and npm
- Docker and Docker Compose v2
- OpenSSL

## Supported Workflows

- Repository-based installation from a cloned repository
- Bundle-based/offline installation from pre-packaged Docker image archives
- Upgrade of an existing installation
- Runtime management: start, stop, restart, and status inspection
- Optional GPIB and Windows Logstash ingestion integrations
- Uninstall and cleanup

## Next Steps

- To install, upgrade, run, or uninstall Parseus, see the [management guide](docs/MANAGEMENT.md).
- To work on Parseus locally, see the [development guide](docs/DEVELOPMENT.md).
- If something fails, see the [troubleshooting guide](docs/TROUBLESHOOTING.md).

## License

Copyright 2026 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights in this software.

This software is licensed under a GPLv3 license.
Please see [LICENSE](LICENSE) and [COPYRIGHT](COPYRIGHT) for more information.
