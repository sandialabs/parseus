SHELL := /bin/bash

# Don't echo recipe commands; only command output (e.g. explicit @echo) will show.
.SILENT:

# Actions
PYTHON := $(shell \
	for p in python3.13 python3.12 python3.11 python3 python; do \
		if command -v $$p >/dev/null 2>&1; then \
			$$p -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1 && { echo $$p; break; }; \
		fi; \
	done \
)

ifeq ($(PYTHON),)
$(error No Python interpreter >= 3.11 found in PATH)
endif

VENV_DIR := .venv
VENV_PYTHON := $(CURDIR)/$(VENV_DIR)/bin/python
VENV_PIP := $(VENV_PYTHON) -m pip
VENV_PARSEUS := $(CURDIR)/$(VENV_DIR)/bin/parseus
VENV_CELERY := $(CURDIR)/$(VENV_DIR)/bin/celery
# constraints.txt pins the full resolved dependency set. PEAT hard-pins requests,
# cryptography, etc., which otherwise sends pip into resolution-too-deep backtracking.
CONSTRAINTS := $(CURDIR)/constraints.txt
PIP_INSTALL = PYTHONWARNINGS="ignore:Unverified HTTPS request" $(VENV_PIP) install --trusted-host pypi.org --trusted-host files.pythonhosted.org --disable-pip-version-check
MANAGE := $(VENV_PYTHON) manage.py
BLACK := black
ISORT := isort
PRETTIER := npx prettier

# Webapp setup variables
PARSEUS_DIR := $(HOME)/.parseus
STORAGE_DIR := $(HOME)/.parseus/artifacts
WEBAPP_DIR := src/parseus/webapp
ENVS_DIR := envs
DEV_ENV = $(ENVS_DIR)/development.env

# Local dev Redis (standalone docker container)
REDIS_CONTAINER := parseus_redis_dev
REDIS_IMAGE := redis:8.10.2

# Local dev Elasticsearch (standalone docker container)
ELASTICSEARCH_CONTAINER := parseus_elasticsearch_dev
ELASTICSEARCH_IMAGE := elasticsearch:8.19.5
ELASTICSEARCH_VOLUME := parseus_elasticsearch_dev_data

# Package variables
APP := parseus
VERSION := $(shell $(PYTHON) -c 'import pathlib, tomllib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')
export PARSEUS_VERSION := $(VERSION)

STAGE := dist/$(APP)-$(VERSION)
ARCHIVE := dist/$(APP)-$(VERSION).tar.gz

ROOT_DOCS := README.md
DOC_DIRS := docs
BUILD_COMPOSE := compose.build.yaml
IMAGES_COMPOSE := compose.images.yaml
ROOT_FILES := pyproject.toml compose.images.yaml compose.runtime.yaml entrypoint.sh manage_parseus.py nginx.conf
MANAGE_LIB_DIR := manage_parseus_lib
INTEGRATIONS_DIR := deploy/integrations

IMAGE_LIST = $$(docker compose -f $(IMAGES_COMPOSE) config --images | awk 'NF && !seen[$$0]++')


# Function to create a Fernet key (reuse manage_parseus minimal generator)
define create_fernet_key
if grep -q "^$(2)=" "$(1)"; then \
	echo "$(2) already exists; leaving it unchanged."; \
else \
	secret_key=$$("$(VENV_PYTHON)" manage_parseus.py create-key --kind fernet); \
	echo "$(2)='$$secret_key'" >> "$(1)"; \
	echo "$(2) has been added."; \
fi
endef

# Function to create a Django SECRET_KEY (reuse manage_parseus minimal generator)
define create_django_key
if grep -q "^$(2)=" "$(1)"; then \
	echo "$(2) already exists; leaving it unchanged."; \
else \
	secret_key=$$("$(VENV_PYTHON)" manage_parseus.py create-key --kind django-secret); \
	echo "$(2)='$$secret_key'" >> "$(1)"; \
	echo "$(2) has been added."; \
fi
endef

# Function to add an environment variable to a .env file
define define_env
if grep -q "^$(2)=" "$(1)"; then \
	sed -i.bak "/^$(2)=/c\$(2)=$(3)" "$(1)" && rm "$(1).bak"; \
else \
	echo "$(2)=$(3)" >> "$(1)"; \
fi
endef


.PHONY: images-pull images-save stage package help setup _install_package _directories _static _tables _create_dev_env run run-celery run-web start-redis start-elasticsearch clean clean-artifacts tests test-python test-js

help:
	@echo "Usage:"
	@echo "  make setup              - Create project directories, dev .env, static files, and database tables"
	@echo "  make tests              - Run every test suite: Python (pytest) and JavaScript (node --test)"
	@echo "  make test-python        - Run the Python tests (tests/ plus app-local tests such as webapp/alerts/tests.py)"
	@echo "  make test-js            - Run the browser-script tests (jsdom; no browser or server needed)"
	@echo "  make start-redis        - Start Redis (background)"
	@echo "  make start-elasticsearch - Start Elasticsearch (background)"
	@echo "  make run                - Start webserver + Celery beat/workers (foreground; Ctrl+C stops)"
	@echo "  make run-web            - Start only the webserver (foreground)"
	@echo "  make run-celery         - Start only Celery (beat + analytics/maintenance worker + single-thread PEAT worker; foreground; Ctrl+C stops)"
	@echo "  make clean              - Clean build/cache files without deleting local Parseus data"
	@echo "  make clean-artifacts    - Delete local Parseus data under $(PARSEUS_DIR)"

# Build local images, then pull required images
images-pull:
	docker compose -f "$(BUILD_COMPOSE)" build
	docker compose -f "$(IMAGES_COMPOSE)" pull

# Save all images in IMAGE_LIST as tar archives in the staging area
images-save: images-pull
	mkdir -p "$(STAGE)/images"
	@for img in $(IMAGE_LIST); do \
		safe_name=$$(echo "$$img" | sed 's#[/:]#_#g'); \
		echo "Saving $$img -> $(STAGE)/images/$$safe_name.tar"; \
		docker save -o "$(STAGE)/images/$$safe_name.tar" "$$img"; \
	done

# Prepare staging directory with images and required deployment files
stage:
	$(MAKE) --no-print-directory clean
	$(MAKE) --no-print-directory images-save
	mkdir -p "$(STAGE)"
	cp $(ROOT_DOCS) "$(STAGE)/"
	cp $(ROOT_FILES) "$(STAGE)/"
	cp -r $(MANAGE_LIB_DIR) "$(STAGE)/"
	cp -r $(DOC_DIRS) "$(STAGE)/"
	mkdir -p "$(STAGE)/deploy"
	cp -r $(INTEGRATIONS_DIR) "$(STAGE)/deploy/"

# Create distributable archive from staged contents
package: stage
	tar -czvf "$(ARCHIVE)" -C dist "$(APP)-$(VERSION)"

# Setup a development environment. Run steps explicitly so `make -j setup` cannot reorder them.
setup:
	$(MAKE) --no-print-directory _install_package
	$(MAKE) --no-print-directory _directories
	$(MAKE) --no-print-directory _create_dev_env
	$(MAKE) --no-print-directory _static
	$(MAKE) --no-print-directory _tables

_install_package:
	$(PYTHON) -m venv "$(VENV_DIR)"
	$(PIP_INSTALL) --upgrade pip
	$(PIP_INSTALL) -c "$(CONSTRAINTS)" -e '.[all,dev]'

# Create directories where the webapp will store data
_directories:
	@echo "Setting up project directories..."
	mkdir -p "$(STORAGE_DIR)"/{database,logs,media,static,pcaps}

# Collect all static files needed by the webapp
_static:
	@echo "Installing the Webapp via NPM"
	cd "$(WEBAPP_DIR)" && npm install
	@echo "Building frontend assets..."
	cd "$(WEBAPP_DIR)" && npm run build
	@echo "Collecting static files..."
	cd "$(WEBAPP_DIR)" && set -a && source "$(CURDIR)/$(DEV_ENV)" && set +a && $(MANAGE) collectstatic --noinput
	@echo "Compressing static files..."
	cd "$(WEBAPP_DIR)" && set -a && source "$(CURDIR)/$(DEV_ENV)" && set +a && $(MANAGE) compress

# Check for database schema changes
_tables:
	@echo "Applying database tables..."
	@set -e; \
		set -a; source "$(CURDIR)/$(DEV_ENV)"; set +a; \
		"$(VENV_PARSEUS)" makemigrations alerts analytics pei registers; \
		"$(VENV_PARSEUS)" migrate; \
		"$(VENV_PARSEUS)" populate_analytics; \
		"$(VENV_PARSEUS)" create_periodic_tasks

# Creates a development .env file
_create_dev_env:
	@mkdir -p $(ENVS_DIR)
	@touch $(DEV_ENV)
	@$(call define_env,$(DEV_ENV),DJANGO_DEBUG,True)
	@$(call define_env,$(DEV_ENV),CELERY_BROKER_URL,redis://localhost:6379/0)
	@$(call create_django_key,$(DEV_ENV),DJANGO_SECRET_KEY)
	@$(call create_fernet_key,$(DEV_ENV),DJANGO_ENCRYPTION_KEY)

# Run every test suite. Steps are explicit (not prerequisites) so `make -j tests`
# cannot reorder them, and the first failing suite stops the run.
tests:
	$(MAKE) --no-print-directory test-python
	$(MAKE) --no-print-directory test-js

# Python tests. pyproject.toml's testpaths cover tests/ AND the app-local tests that
# live beside their app (e.g. webapp/alerts/tests.py). Some tests in tests/ talk to a
# real datastore at DATASTORE_HOST_URL (default http://localhost:9200); run
# `make start-elasticsearch` first. Extra pytest arguments: make test-python PYTEST_ARGS="-k alerts"
PYTEST_ARGS ?=
test-python:
	@echo "Running Python tests..."
	"$(VENV_PYTHON)" -m pytest $(PYTEST_ARGS)

# Browser-script tests (node:test + jsdom): no browser or server needed. jsdom is a
# devDependency installed into node_modules, which `make clean` deletes, so install
# it on demand rather than failing with a confusing "Cannot find module".
test-js:
	@echo "Running JavaScript tests..."
	@cd "$(WEBAPP_DIR)" && { [ -d node_modules/jsdom ] || npm install --no-audit --no-fund; } && npm test

# Remove generated build/cache files. This intentionally preserves local data in $(PARSEUS_DIR).
clean:
	@echo "Removing node folders..."
	rm -rf "$(WEBAPP_DIR)/node_modules/"
	rm -rf "$(WEBAPP_DIR)/dist/"
	rm -rf "$(WEBAPP_DIR)/package-lock.json"
	@echo "Removing build folders..."
	rm -rf "$(STAGE)"
	rm -rf "$(ARCHIVE)"
	@echo "Removing Python/cache files..."
	find . \( -path './.git' -o -path './$(VENV_DIR)' -o -path './$(WEBAPP_DIR)/node_modules' \) -prune -o -name "*.py[cod]" -type f -exec rm -f {} +
	find . \( -path './.git' -o -path './$(VENV_DIR)' -o -path './$(WEBAPP_DIR)/node_modules' \) -prune -o -name "*.egg-info" -type d -prune -exec rm -rf {} +
	find . \( -path './.git' -o -path './$(VENV_DIR)' -o -path './$(WEBAPP_DIR)/node_modules' \) -prune -o -name "*.log" -type f -exec rm -f {} +
	find . \( -path './.git' -o -path './$(VENV_DIR)' -o -path './$(WEBAPP_DIR)/node_modules' \) -prune -o -name "*~" -type f -exec rm -f {} +
	find . \( -path './.git' -o -path './$(VENV_DIR)' -o -path './$(WEBAPP_DIR)/node_modules' \) -prune -o -name "__pycache__" -type d -prune -exec rm -rf {} +
	find . \( -path './.git' -o -path './$(VENV_DIR)' -o -path './$(WEBAPP_DIR)/node_modules' \) -prune -o -name ".cache" -type d -prune -exec rm -rf {} +
	find . \( -path './.git' -o -path './$(VENV_DIR)' -o -path './$(WEBAPP_DIR)/node_modules' \) -prune -o -name "celerybeat-schedule*" -type f -exec rm -f {} +

clean-artifacts:
	@echo "Removing local Parseus data under $(PARSEUS_DIR)..."
	rm -rf "$(PARSEUS_DIR)"

# Starts Redis in the background (standalone container)
start-redis:
	@set -e; \
	if docker ps --format '{{.Names}}' | grep -qx "$(REDIS_CONTAINER)"; then \
		echo "Redis already running."; \
		exit 0; \
	fi; \
	echo "Starting Redis..."; \
	docker rm -f "$(REDIS_CONTAINER)" >/dev/null 2>&1 || true; \
	docker run -d --name "$(REDIS_CONTAINER)" -p 127.0.0.1:6379:6379 "$(REDIS_IMAGE)" >/dev/null; \
	: "Wait for Redis broker readiness"; \
	for i in $$(seq 1 30); do \
		if docker exec "$(REDIS_CONTAINER)" redis-cli ping >/dev/null 2>&1; then \
			break; \
		fi; \
		sleep 0.2; \
	done; \
	if ! docker exec "$(REDIS_CONTAINER)" redis-cli ping >/dev/null 2>&1; then \
		echo "Redis did not become ready in time."; \
		exit 1; \
	fi; \
	echo "Redis ready."

# Starts Elasticsearch in the background (standalone container)
start-elasticsearch:
	@set -e; \
	if docker ps --format '{{.Names}}' | grep -qx "$(ELASTICSEARCH_CONTAINER)"; then \
		echo "Elasticsearch already running."; \
		exit 0; \
	fi; \
	echo "Starting Elasticsearch..."; \
	docker rm -f "$(ELASTICSEARCH_CONTAINER)" >/dev/null 2>&1 || true; \
	docker run -d --name "$(ELASTICSEARCH_CONTAINER)" \
		-e discovery.type=single-node \
		-e xpack.security.enabled=false \
		-e ES_JAVA_OPTS='-Xms2g -Xmx2g' \
		-v "$(ELASTICSEARCH_VOLUME)":/usr/share/elasticsearch/data \
		-p 127.0.0.1:9200:9200 \
		-p 127.0.0.1:9300:9300 \
		"$(ELASTICSEARCH_IMAGE)" >/dev/null; \
	: "Wait for Elasticsearch readiness"; \
	if ! command -v curl >/dev/null 2>&1; then \
		echo "curl not found; please install curl to allow readiness checks."; \
		exit 1; \
	fi; \
	for i in $$(seq 1 60); do \
		if curl -fsS "http://127.0.0.1:9200/_cluster/health" >/dev/null 2>&1; then \
			break; \
		fi; \
		sleep 0.5; \
	done; \
	if ! curl -fsS "http://127.0.0.1:9200/_cluster/health" >/dev/null 2>&1; then \
		echo "Elasticsearch did not become ready in time."; \
		exit 1; \
	fi; \
	echo "Elasticsearch ready."


# Starts Parseus webserver only (foreground)
run-web:
	@set -e; \
		echo "Loading environment variables from $(DEV_ENV)..."; \
		set -a; source "$(CURDIR)/$(DEV_ENV)"; set +a; \
		echo "Starting Parseus webserver..."; \
		"$(VENV_PARSEUS)" runserver localhost:8080

# Start only Celery (beat + analytics/maintenance worker + PEAT worker; foreground; Ctrl+C stops)
run-celery:
	@set -e; \
		echo "Loading environment variables from $(DEV_ENV)..."; \
		set -a; source "$(CURDIR)/$(DEV_ENV)"; set +a; \
		echo "Starting Celery beat..."; \
		"$(VENV_CELERY)" -A src.parseus.webapp.project beat --loglevel=info & BEAT_PID=$$!; \
		echo "Starting Celery analytics/maintenance worker..."; \
		"$(VENV_CELERY)" -A src.parseus.webapp.project worker -Q analytics,maintenance --loglevel=info & SCHEDULER_WORKER_PID=$$!; \
		echo "Starting Celery PEAT worker (single-threaded)..."; \
		"$(VENV_CELERY)" -A src.parseus.webapp.project worker -Q peat --concurrency=1 --prefetch-multiplier=1 -Ofair --loglevel=info & PEAT_WORKER_PID=$$!; \
		cleanup() { echo "Stopping services..."; kill $$BEAT_PID $$SCHEDULER_WORKER_PID $$PEAT_WORKER_PID 2>/dev/null || true; wait $$BEAT_PID $$SCHEDULER_WORKER_PID $$PEAT_WORKER_PID 2>/dev/null || true; }; \
		trap 'cleanup; exit 130' INT; \
		trap 'cleanup; exit 143' TERM; \
		echo "Celery services started (beat + analytics/maintenance worker + single-thread PEAT worker). Press Ctrl+C to stop."; \
		status=0; \
		wait -n $$BEAT_PID $$SCHEDULER_WORKER_PID $$PEAT_WORKER_PID || status=$$?; \
		cleanup; \
		exit $$status

# Starts Parseus webserver + Celery beat + Celery workers (foreground; Ctrl+C stops all)
run:
	@set -e; \
		echo "Loading environment variables from $(DEV_ENV)..."; \
		set -a; source "$(CURDIR)/$(DEV_ENV)"; set +a; \
		echo "Starting Celery beat..."; \
		"$(VENV_CELERY)" -A src.parseus.webapp.project beat --loglevel=info & BEAT_PID=$$!; \
		echo "Starting Celery analytics/maintenance worker..."; \
		"$(VENV_CELERY)" -A src.parseus.webapp.project worker -Q analytics,maintenance --loglevel=info & SCHEDULER_WORKER_PID=$$!; \
		echo "Starting Celery PEAT worker (single-threaded)..."; \
		"$(VENV_CELERY)" -A src.parseus.webapp.project worker -Q peat --concurrency=1 --prefetch-multiplier=1 -Ofair --loglevel=info & PEAT_WORKER_PID=$$!; \
		echo "Starting Parseus webserver..."; \
		"$(VENV_PARSEUS)" runserver localhost:8080 & WEB_PID=$$!; \
		cleanup() { echo "Stopping services..."; kill $$BEAT_PID $$SCHEDULER_WORKER_PID $$PEAT_WORKER_PID $$WEB_PID 2>/dev/null || true; wait $$BEAT_PID $$SCHEDULER_WORKER_PID $$PEAT_WORKER_PID $$WEB_PID 2>/dev/null || true; }; \
		trap 'cleanup; exit 130' INT; \
		trap 'cleanup; exit 143' TERM; \
		status=0; \
		wait -n $$BEAT_PID $$SCHEDULER_WORKER_PID $$PEAT_WORKER_PID $$WEB_PID || status=$$?; \
		cleanup; \
		exit $$status
