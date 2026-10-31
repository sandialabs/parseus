# Parseus Troubleshooting

## Verify platform and required software

The management script supports Linux (x86_64 / AMD64 only). Verify required tools:

    python3 --version

The host `python3` only needs to be 3.8 or later to run the management script. The Parseus application's own 3.11 - 3.13 requirement applies to development from source, not to deployment.
    docker --version
    docker compose version
    openssl version

The script checks for Docker Compose v2 as `docker compose`; it does not use the legacy `docker-compose` command.

## Verify Docker access

If a management command fails before containers start, confirm Docker is running and accessible:

    docker info

Common causes of failure include:

- Docker service is not running
- the current user cannot access the Docker daemon
- the Docker daemon is unreachable

On Linux, permission issues may require adding your user to the `docker` group and starting a new session, or running the command with elevated privileges if appropriate. Parseus management privileges (the `parseus-admin` group) and Docker daemon access are separate: a `parseus-admin` member who runs `up`, `down`, or `restart` also needs Docker access. If they do not have it, Parseus stops with a clear message explaining that the Docker daemon is reachable but the user cannot access it, and suggests either running the command with `sudo` or being granted Docker access. Note that membership in the `docker` group grants root-equivalent access to the host, so it should be granted deliberately.

## Verify required ports

The management script checks published host ports from the rendered Docker Compose configuration before starting the stack. Common ports include `80`, `443`, and ports required by enabled integrations.

Inspect listening ports:

    ss -ltnp

Inspect individual ports:

    lsof -i :80
    lsof -i :443

If a required port is in use by another service, stop that service or change the Compose port mapping.

## Verify required images

If install or upgrade fails after image build, pull, or load, inspect local images:

    docker image ls

The script determines required images from the rendered Docker Compose configuration for the selected integrations. Repository installs expect required images to be built or pulled successfully. Bundle installs expect image archives under:

    images/

If images are missing or tagged differently, rebuild repository images or recreate the bundle.

## Verify bundle contents

An extracted bundle should contain at least:

- `manage_parseus.py`
- `compose.images.yaml`
- `compose.runtime.yaml`
- `nginx.conf`
- `entrypoint.sh`
- `deploy/integrations/`
- `images/`

The `images/` directory must contain `.tar`, `.tgz`, or `.tar.gz` Docker image archives.

## `manage-parseus` permission or sudo path errors

The installed command wrapper lives at:

    /usr/local/bin/manage-parseus

If running `manage-parseus` as a regular user prints `Permission denied`, inspect the wrapper and target permissions:

    ls -l /usr/local/bin/manage-parseus
    readlink -f /usr/local/bin/manage-parseus
    ls -l /opt/parseus/manage_parseus.py

The wrapper should resolve to `/opt/parseus/manage_parseus.py`, and the target script should be executable. Privilege requirements differ by command: `status`, `up`, `down`, and `restart` can be run with `sudo` or by a member of the `parseus-admin` group; `install`, `upgrade`, and `uninstall` need root; and `sample-config`, `create-key`, and `validate-config` need no special privileges. To optionally run status and runtime commands without `sudo`, add your user with `sudo usermod -aG parseus-admin <user>` and re-login.

If `sudo manage-parseus ...` prints `command not found`, your sudo configuration may use a restricted `secure_path` that does not include `/usr/local/bin`. Run the wrapper by full path instead:

    sudo /usr/local/bin/manage-parseus status

or ask the system administrator to include `/usr/local/bin` in sudo's secure path.

## Verify containers are running

From the installation root, check status:

    docker compose -f compose.images.yaml -f compose.runtime.yaml ps

If Parseus was installed into a non-default location, run the command from that installation root or provide full paths to both Compose files.

Warning signs include containers that are `Exited`, `Restarting`, `unhealthy`, or missing.

Check logs:

    docker logs <container-name>

List all containers:

    docker ps -a

## Parseus does not open in the browser

After install, upgrade, start, or restart, Parseus should be available at:

    https://127.0.0.1/

If the page does not load:

- confirm the management command completed successfully
- confirm required containers are running
- confirm port `443` is listening
- wait briefly and try again, especially after first startup

Automatic browser launch requires a graphical Linux session and `xdg-open` in `PATH`. If automatic launch is unavailable, open the printed URL manually.

## Browser certificate warning

The default deployment generates a self-signed HTTPS certificate. Browser certificate warnings are expected unless you replace the certificate with one trusted by your environment.

## Optional components are missing

Available integrations are:

- `gpib`
- `winlog`

If an expected optional service is missing:

- confirm which integrations were used during installation
- remember that upgrade, up, and restart reuse manifest integrations when `--integrations` is omitted
- rerun the appropriate command with the required `--integrations` value

## Start over with a clean installation

To remove the current deployment:

    sudo manage-parseus uninstall

To retain manifest-recorded images:

    sudo manage-parseus uninstall --keep-images

To also remove the Winlog ingest drop directory and installer-created system accounts:

    sudo manage-parseus uninstall --purge-ingest-drop --remove-system-account

> Warning: uninstall may permanently delete stored application data.

## Information to gather for support

Before requesting support, gather:

- exact management command executed
- repository or bundle workflow used
- installation root
- enabled integrations
- full management script output
- container status
- relevant container logs
- operating system details
- Docker version
- Docker Compose version
