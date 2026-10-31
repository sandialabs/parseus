import io
import json
import logging
import mimetypes
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import yaml
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View
from peat import generate_simple_config, module_api

from parseus.webapp.project.views import get_database_status, get_database_url

from .forms import PeatBuilderForm, PeatConfigForm, PeatDeviceForm
from .models import PeatConfig, PeatDevice, PeatPull, PeatScan
from .peat_locks import (
    PeatLockError,
    acquire_target_locks,
    build_owner_token_for_run,
    release_owner_locks,
    resolve_lock_targets,
)
from .tasks import peat_pull, peat_scan

LOGGER = logging.getLogger(__name__)


class PeatTargetSelectionError(ValueError):
    """Raised when selected configured hosts cannot form one PEAT invocation."""


def index(request):
    """Render the peat home page."""
    return render(request, "peat/home.html")


def get_peat_modules(request):
    return JsonResponse(module_api.names, safe=False)


def get_peat_module_defaults(request, module_name):
    """Return the default options that PEAT generates for a module."""
    matching_module = next(
        (
            peat_module
            for peat_module in module_api.names
            if peat_module.lower() == module_name.lower()
        ),
        None,
    )
    if not matching_module:
        return JsonResponse({"message": "Unknown PEAT module."}, status=404)

    config_yaml = generate_simple_config(
        [("127.0.0.1", "default-options-preview", matching_module)]
    )
    config_data = yaml.safe_load(config_yaml) or {}
    hosts = config_data.get("hosts") or []
    options = hosts[0].get("options", {}) if hosts else {}
    return JsonResponse(convert_tuples_to_dict(options or {}), safe=False)


def convert_tuples_to_dict(data):
    """Converts python tuples to dicts because YAML doesn't understand what that is."""
    if isinstance(data, list):
        # If the data is a list, iterate through its elements
        return [convert_tuples_to_dict(item) for item in data]
    elif isinstance(data, tuple):
        # If the data is a tuple, convert it to a dictionary
        if len(data) == 2:
            return {data[0]: data[1]}  # Convert tuple to dict with key-value pair
        else:
            return list(data)  # If tuple has more than 2 elements, return as list
    elif isinstance(data, dict):
        # If the data is a dictionary, recursively process its values
        return {key: convert_tuples_to_dict(value) for key, value in data.items()}
    else:
        # If it's neither a list, tuple, nor dict, return it as is
        return data


def get_run_objects(request, method):
    data = json.loads(request.body or "{}")
    pk = data.get("config")
    default_only = data.get("default_only", False)
    if method == "pull":
        peat_run_query = PeatPull.objects.all()
    elif method == "scan":
        peat_run_query = PeatScan.objects.all()
    else:
        raise Http404("method is not pull or scan")

    if pk:
        peat_run_query = peat_run_query.filter(config_id=pk)
    elif default_only:
        peat_run_query = peat_run_query.filter(config__isnull=True)

    peat_run_objs = list(peat_run_query.order_by("-created").values())
    return JsonResponse(peat_run_objs, safe=False)


def peatScanConfigView(request):
    return render(request, "peat/peat_scan.html", {"peat_modules": module_api.names})


def clean_directory_name(name):
    allowed_characters = re.compile(r"[^a-zA-Z0-9_\- ]")
    cleaned_name = allowed_characters.sub("_", name or "")
    cleaned_name = cleaned_name.strip()
    return cleaned_name


def parse_default_targets(targets):
    """Return a normalized target list from default-run form/API input."""
    if isinstance(targets, list):
        raw_targets = targets
    else:
        raw_targets = re.split(r"[\n,]+", str(targets or ""))
    return [str(target).strip() for target in raw_targets if str(target).strip()]


def get_peat_run_name(method, requested_name):
    """Return the user-provided run name or a unique default run name."""
    cleaned_name = clean_directory_name(requested_name)
    if cleaned_name:
        return cleaned_name
    return f"peat_{method}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S%f')}"


def _format_device_target(device, target):
    return f"{device.label}: {target}" if device.label else str(target)


def parse_default_modules(modules):
    """Return normalized PEAT module names selected for a default run."""
    if modules is None:
        return ["all"]
    if isinstance(modules, list):
        raw_modules = modules
    else:
        raw_modules = re.split(r"[\n,]+", str(modules or ""))

    raw_modules = [str(module).strip() for module in raw_modules if str(module).strip()]
    if not raw_modules or any(module.lower() == "all" for module in raw_modules):
        return ["all"]

    selected_modules = set()
    invalid_modules = []
    for module in raw_modules:
        module_names = module_api.lookup_names([module])
        if not module_names:
            invalid_modules.append(module)
        selected_modules.update(module_names)

    if invalid_modules:
        invalid_list = ", ".join(invalid_modules)
        raise ValidationError(f"Unknown PEAT module selection: {invalid_list}")

    return sorted(selected_modules)


def get_selected_config_targets(config_pk, device_ids):
    """Return display labels, targets, and PEAT target mode for selected devices.

    PEAT's CLI accepts network targets through ``-i`` and serial targets through
    ``-s``. A single PEAT invocation cannot mix those mutually-exclusive modes,
    so mixed selections are rejected instead of silently dropping hosts.
    """
    device_list = []
    network_targets = []
    serial_targets = []
    unsupported_devices = []

    peat_devices = PeatDevice.objects.filter(config_id=config_pk, id__in=device_ids)
    for device in peat_devices:
        if device.ip:
            target = str(device.ip)
            device_list.append(_format_device_target(device, target))
            network_targets.append(target)
        elif device.hostname:
            target = str(device.hostname)
            device_list.append(_format_device_target(device, target))
            network_targets.append(target)
        elif device.serial_port:
            target = str(device.serial_port)
            device_list.append(_format_device_target(device, target))
            serial_targets.append(target)
        else:
            unsupported_devices.append(str(device.label or device.pk))

    if unsupported_devices:
        raise PeatTargetSelectionError(
            "Selected host(s) do not have an IP address, hostname, or serial "
            "port PEAT can target from the webapp: "
            + ", ".join(unsupported_devices)
        )
    if network_targets and serial_targets:
        raise PeatTargetSelectionError(
            "Selected hosts mix network targets and serial targets. Run network "
            "and serial hosts separately."
        )

    if serial_targets:
        return device_list, serial_targets, "serial"
    return device_list, network_targets, "ip"


def _format_busy_lock_message(busy_targets):
    """Return a concise message for targets locked by another PEAT run."""
    displayed_targets = busy_targets[:10]
    target_list = ", ".join(displayed_targets)
    if len(busy_targets) > len(displayed_targets):
        target_list += f", and {len(busy_targets) - len(displayed_targets)} more"
    return f"PEAT target(s) are already in use: {target_list}"


def _busy_lock_response(busy_targets):
    """Return a response body that the frontend can use to prompt queueing."""
    return {
        "status": False,
        "reason": "targets_busy",
        "can_queue": True,
        "message": _format_busy_lock_message(busy_targets),
        "busy_targets": busy_targets,
    }


def _format_busy_target_display(display_target, requested_target, resolved_target):
    """Return a user-facing busy target label without hiding lock identity."""
    display_target = str(display_target)
    requested_target = str(requested_target)
    resolved_target = str(resolved_target)
    if resolved_target in display_target:
        return display_target
    if requested_target and requested_target != resolved_target:
        return f"{display_target} ({resolved_target})"
    return display_target


def _build_busy_target_display_map(display_targets, targets, target_mode):
    """Map concrete lock targets back to the labels shown in config-based runs."""
    display_by_target = {}
    for display_target, requested_target in zip(display_targets, targets):
        for resolved_target in resolve_lock_targets([requested_target], target_mode):
            display_by_target.setdefault(
                resolved_target.target,
                _format_busy_target_display(
                    display_target,
                    requested_target,
                    resolved_target.target,
                ),
            )
    return display_by_target


def _display_busy_targets(busy_targets, display_by_target):
    """Return busy targets with configured device labels when available."""
    return [display_by_target.get(target, target) for target in busy_targets]


def _resolve_peat_targets_for_queue(targets, target_mode):
    """Return concrete target strings to keep queued PEAT runs deterministic."""
    return [target.target for target in resolve_lock_targets(targets, target_mode)]


def _release_peat_locks_safely(owner):
    """Release Redis PEAT locks without masking the original view error."""
    if not owner:
        return
    try:
        release_owner_locks(owner)
    except Exception:
        LOGGER.exception("Failed to release PEAT locks for %s", owner)


def _delete_unscheduled_run(peat_run_obj):
    """Delete a run object that was saved only to derive a lock owner token."""
    if not peat_run_obj.pk:
        return
    try:
        peat_run_obj.delete()
    except Exception:
        LOGGER.exception("Failed to delete unscheduled PEAT run %s", peat_run_obj.pk)


def _load_json_file(path: Path):
    try:
        with path.open(encoding="utf-8") as file_obj:
            return json.load(file_obj)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _human_file_size(size):
    try:
        size = int(size)
    except (TypeError, ValueError):
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value = value / 1024
    return f"{size} B"


def _build_run_file_url(method, run_pk, relative_path, *, download=False):
    query_params = {"path": relative_path}
    if download:
        query_params["download"] = "1"
    file_url = reverse("peat:peatRun-file", kwargs={"method": method, "pk": run_pk})
    return f"{file_url}?{urlencode(query_params)}"


def _safe_relative_file(root: Path, file_path: Path, method=None, run_pk=None):
    try:
        resolved = file_path.resolve()
        resolved.relative_to(root)
        stat = resolved.stat()
    except (FileNotFoundError, OSError, ValueError):
        return None
    relative_path = resolved.relative_to(root).as_posix()
    file_info = {
        "path": relative_path,
        "name": resolved.name,
        "size": stat.st_size,
        "size_display": _human_file_size(stat.st_size),
        "modified": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat(timespec="seconds"),
    }
    if method and run_pk:
        file_info["view_url"] = _build_run_file_url(method, run_pk, relative_path)
        file_info["download_url"] = _build_run_file_url(
            method, run_pk, relative_path, download=True
        )
    return file_info


def _read_device_summary(device_dir: Path, root: Path, method=None, run_pk=None):
    summary_path = device_dir / "device-data-summary.json"
    summary = _load_json_file(summary_path)
    if not isinstance(summary, dict):
        return None

    files = [
        file_info
        for file_info in (
            _safe_relative_file(root, file_path, method, run_pk)
            for file_path in sorted(device_dir.rglob("*"))
            if file_path.is_file() and not file_path.is_symlink()
        )
        if file_info
    ]
    related = summary.get("related") or {}
    description = summary.get("description") or {}
    firmware = summary.get("firmware") or {}
    hardware = summary.get("hardware") or {}
    os_info = summary.get("os") or {}

    return {
        "id": summary.get("label")
        or summary.get("id")
        or summary.get("ip")
        or summary.get("hostname")
        or summary.get("serial_port")
        or device_dir.name,
        "directory": device_dir.relative_to(root).as_posix(),
        "type": summary.get("type", ""),
        "description": description.get("full") or description.get("product") or "",
        "vendor": (description.get("vendor") or {}).get("name", ""),
        "ip": summary.get("ip", ""),
        "hostname": summary.get("hostname", ""),
        "mac": summary.get("mac", ""),
        "serial_port": summary.get("serial_port", ""),
        "serial_number": summary.get("serial_number", ""),
        "part_number": summary.get("part_number", ""),
        "uptime": summary.get("uptime", ""),
        "os": os_info.get("full") or os_info.get("name") or "",
        "firmware": firmware.get("version") or firmware.get("revision") or "",
        "hardware": hardware.get("version") or hardware.get("revision") or hardware.get("id") or "",
        "run_mode": summary.get("run_mode", ""),
        "status": summary.get("status", ""),
        "counts": {
            "files": len(files),
            "services": len(summary.get("service") or []),
            "interfaces": len(summary.get("interface") or []),
            "events": len(summary.get("event") or []),
            "registers": len(summary.get("registers") or summary.get("register") or []),
            "tags": len(summary.get("tag") or []),
            "io": len(summary.get("io") or []),
            "users": len(summary.get("users") or []),
            "related_files": len(related.get("files") or []),
            "related_ips": len(related.get("ip") or []),
            "related_protocols": len(related.get("protocols") or []),
        },
        "top_files": files[:8],
    }


def _build_run_file_tree(root: Path, method=None, run_pk=None, limit=None):
    nodes = []
    total_files = 0
    total_dirs = 0
    total_bytes = 0
    files_by_section = {}

    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            continue
        try:
            relative_path = path.resolve().relative_to(root)
        except (OSError, ValueError):
            continue
        section = relative_path.parts[0] if relative_path.parts else "."
        include_node = limit is None or len(nodes) < limit
        relative_path_text = relative_path.as_posix()

        if path.is_dir():
            total_dirs += 1
            if include_node:
                nodes.append(
                    {
                        "path": relative_path_text,
                        "name": path.name,
                        "type": "dir",
                    }
                )
            continue
        if not path.is_file():
            continue

        stat = path.stat()
        total_files += 1
        total_bytes += stat.st_size
        files_by_section[section] = files_by_section.get(section, 0) + 1
        if include_node:
            node = {
                "path": relative_path_text,
                "name": path.name,
                "type": "file",
                "size": stat.st_size,
                "size_display": _human_file_size(stat.st_size),
            }
            if method and run_pk:
                node["view_url"] = _build_run_file_url(method, run_pk, relative_path_text)
                node["download_url"] = _build_run_file_url(
                    method, run_pk, relative_path_text, download=True
                )
            nodes.append(node)

    return {
        "nodes": nodes,
        "truncated": limit is not None and (total_files + total_dirs) > len(nodes),
        "total_files": total_files,
        "total_dirs": total_dirs,
        "total_size": total_bytes,
        "total_size_display": _human_file_size(total_bytes),
        "files_by_section": files_by_section,
    }


def _get_peat_run_details(obj, method):
    parent_run_dir = settings.PEAT_PULL_DIR if method == "pull" else settings.PEAT_SCAN_DIR
    run_dir = obj.run_dir
    response = {
        "method": method,
        "status": obj.status,
        "run_dir": run_dir,
        "name": obj.name,
        "created": obj.created.isoformat() if obj.created else None,
        "targets": obj.devices or [],
        "modules": obj.modules or [],
        "config": {"id": obj.config_id, "name": obj.config.name} if obj.config else None,
        "output_exists": False,
        "summary_available": False,
        "devices": [],
        "tree": {"nodes": [], "total_files": 0, "total_dirs": 0, "total_size_display": "0 B"},
        "important_files": [],
        "counts": {},
        "outcome": {"severity": "info", "title": "Run data is not available yet.", "message": "PEAT has not written a run directory for this job yet."},
    }
    if not run_dir:
        return response
    if obj.status == "waiting":
        response["outcome"] = {"severity": "info", "title": "Run is waiting for target locks.", "message": "PEAT will start this run when the selected targets are no longer in use."}
        return response

    parent_run_dir = Path(parent_run_dir).resolve()
    root = (parent_run_dir / run_dir).resolve()
    try:
        root.relative_to(parent_run_dir)
    except ValueError:
        response["outcome"] = {"severity": "danger", "title": "Invalid run directory.", "message": "The saved run directory is outside the expected PEAT output location."}
        return response

    if not root.is_dir():
        response["outcome"] = {"severity": "warning", "title": "Run files are not available.", "message": "The database has a run directory name, but the directory is not present on disk."}
        return response

    response["output_exists"] = True
    summary_path = root / "summaries" / f"{method}-summary.json"
    summary = _load_json_file(summary_path)
    if isinstance(summary, dict):
        response["summary_available"] = True

    response["tree"] = _build_run_file_tree(root, method, obj.pk)
    for relative in [
        Path("summaries") / f"{method}-summary.json",
        Path("logs") / "console.log",
        Path("logs") / "peat.log",
        Path("logs") / "json-log.jsonl",
        Path("logs") / "debug-info.txt",
        Path("peat_metadata") / "peat_configuration.yaml",
        Path("peat_metadata") / "peat_state.json",
    ]:
        file_info = _safe_relative_file(root, root / relative, method, obj.pk)
        if file_info:
            response["important_files"].append(file_info)

    devices_dir = root / "devices"
    if devices_dir.is_dir():
        device_roots = [path for path in sorted(devices_dir.iterdir()) if path.is_dir()]
    elif (root / "device-data-summary.json").is_file():
        device_roots = [root]
    else:
        device_roots = []
    response["devices"] = [
        device
        for device in (
            _read_device_summary(device_dir, root, method, obj.pk)
            for device_dir in device_roots
        )
        if device
    ]

    summary_devices_key = "pull_results" if method == "pull" else "hosts_verified"
    summary_devices = summary.get(summary_devices_key, []) if isinstance(summary, dict) else []
    device_count = max(len(response["devices"]), len(summary_devices or []))
    files_by_section = response["tree"].get("files_by_section", {})
    response["counts"] = {
        "targets": len(obj.devices or []),
        "devices": device_count,
        "files": response["tree"].get("total_files", 0),
        "directories": response["tree"].get("total_dirs", 0),
        "logs": files_by_section.get("logs", 0),
        "summaries": files_by_section.get("summaries", 0),
        "metadata": files_by_section.get("peat_metadata", 0),
        "elastic": files_by_section.get("elastic_data", 0),
        "hosts_online": summary.get("num_hosts_online") if isinstance(summary, dict) else None,
        "hosts_verified": summary.get("num_hosts_verified") if isinstance(summary, dict) else None,
    }

    completed = obj.status in {"done", "error", "stopped"}
    if obj.status == "error" and method == "scan" and device_count == 0:
        response["outcome"] = {"severity": "warning", "title": "No devices were identified.", "message": "PEAT completed the scan workflow but did not positively identify any supported devices. Review targets, reachability, selected modules, and the console log before treating this as an application failure."}
    elif completed and device_count == 0:
        response["outcome"] = {"severity": "warning" if method == "scan" else "info", "title": "No devices found in this run.", "message": "The run produced files, but no device-level summaries were found. This can be a valid scan result when no hosts match PEAT's device fingerprints."}
    elif obj.status == "error":
        response["outcome"] = {"severity": "danger", "title": "Run ended with an error.", "message": "Some files may still be useful. Check the console, PEAT logs, and any partial device folders below."}
    elif obj.status == "stopped":
        response["outcome"] = {"severity": "warning", "title": "Run was stopped.", "message": "Partial output may be available. Download the run or inspect the files listed below."}
    elif obj.status == "waiting":
        response["outcome"] = {"severity": "info", "title": "Run is waiting for target locks.", "message": "PEAT will start this run when the selected targets are no longer in use."}
    elif obj.status in {"running", "started"}:
        response["outcome"] = {"severity": "info", "title": "Run is still in progress.", "message": "Summary information will continue to update as PEAT writes files."}
    else:
        response["outcome"] = {"severity": "success", "title": "Run completed with device data.", "message": "Use the device cards, important files, and directory map to decide what to inspect or compare with future runs."}
    return response


class PeatConfigListView(ListView):
    """Django template to handle context and rendering all peat configs
    we have stored."""

    model = PeatConfig
    template_name = "peat/peatconfig_list.html"
    paginate_by = 10
    ordering = ["-updated"]

    def delete(self, request):
        body_dict = json.loads(request.body)
        ids = body_dict.get("ids")
        PeatConfig.objects.filter(id__in=ids).delete()
        return JsonResponse({"message": "success"}, status=204)


class PeatConfigDetailView(DetailView):
    """Django template to handle context and rendering details of a
    peat config."""

    model = PeatConfig
    template_name = "peat/peatconfig_detail.html"

    def post(self, request):
        peat_config = self.get_object()
        peat_pulls = list(peat_config.pulls.all().values())
        return JsonResponse(peat_pulls, safe=False)


class PeatConfigCreateView(CreateView):
    """Django renderer and handler to create a new peat config based
    on the PeatConfigFrom."""

    template_name = "peat/peatconfig_form.html"
    model = PeatConfig
    form_class = PeatConfigForm

    def get_success_url(self):
        return reverse("peat:peatconfig-details", kwargs={"pk": self.object.pk})


class PeatBuilderView(CreateView):
    """Django renderer and handler to create a new peat config based
    on the PeatBuilderFrom."""

    template_name = "peat/peatconfig_build.html"
    model = PeatConfig
    form_class = PeatBuilderForm

    def get_success_url(self):
        return reverse("peat:peatconfig-details", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        device_names = self.request.POST.getlist("device-name")
        device_ips = self.request.POST.getlist("device-ip")
        device_modules = self.request.POST.getlist("device-module")
        device_options = self.request.POST.getlist("device-options")
        devices = [
            (device_ips[i], device_names[i], device_modules[i])
            for i in range(len(device_names))
        ]

        config_yaml = generate_simple_config(devices)
        config_data = yaml.safe_load(config_yaml) or {}
        hosts = config_data.get("hosts", [])
        for index, raw_options in enumerate(device_options):
            raw_options = raw_options.strip()
            if not raw_options:
                continue
            try:
                options = json.loads(raw_options)
            except json.JSONDecodeError:
                form.add_error(None, f"Device {index + 1} has invalid JSON options.")
                return self.form_invalid(form)
            if index < len(hosts):
                hosts[index]["options"] = options
        config_yaml = yaml.dump(config_data, default_flow_style=False, sort_keys=False)

        config_filename = "autobuilt_config_" + str(datetime.now(timezone.utc).date()) + ".yml"
        config_file = ContentFile(config_yaml.encode("utf-8"), name=config_filename)

        instance = form.save(commit=False)
        instance.filename.save(config_filename, config_file, save=False)
        instance.save()

        return super().form_valid(form)


class PeatConfigUpdateView(UpdateView):
    """Django renderer and handler to create a new peat config based
    on the PeatConfigFrom."""

    template_name = "peat/peatconfig_form.html"
    model = PeatConfig
    form_class = PeatConfigForm

    def get_success_url(self):
        # Redirect to the detail view of the updated instance
        return reverse("peat:peatconfig-details", kwargs={"pk": self.object.pk})


class PeatDeviceUpdateView(UpdateView):
    """Django renderer and handler to update a device details based
    on the PeatDeviceFrom."""

    template_name = "peat/peatdevice_form.html"
    model = PeatDevice
    form_class = PeatDeviceForm

    def get_success_url(self):
        # Redirect to the detail view of the updated instance
        return reverse("peat:peatconfig-details", kwargs={"pk": self.object.config.pk})


class PeatRunView(DetailView):
    """Django super class of selected peat pull or scan."""

    def get(self, request):
        search_pk = request.GET.get("pk", "")
        obj = get_object_or_404(self.model, pk=search_pk)
        method = self.model.get_method()
        if method not in {"pull", "scan"}:
            raise Http404("method is not pull or scan")
        return JsonResponse(_get_peat_run_details(obj, method), safe=False)

    def delete(self, request):
        body_dict = json.loads(request.body)
        ids = body_dict.get("ids")
        if ids:
            self.model.objects.filter(id__in=ids).delete()
        return JsonResponse({"message": "success"}, status=204)


class PeatPullView(PeatRunView):
    """Django handler to create a new peat pull and signal celery to start the pull asynchronously
    using the peat interface."""

    model = PeatPull
    template_name = "peat/peatpull_detail.html"

    def post(self, request):
        data = json.loads(request.body)
        config_pk = data.get("config")
        device_ids = data.get("device_ids", [])
        name = get_peat_run_name("pull", data.get("peat_run_name"))
        baseline = data.get("peat_run_baseline", False)
        push = data.get("peat_run_push", False)
        queue_if_busy = data.get("queue_if_busy", False)
        url = None
        if push:
            response = get_database_status(request=request)
            status = json.loads(response.content)["status"]
            if not status:
                return response
            url = get_database_url(request=request)

        peat_config = None
        target_mode = "ip"
        device_list = []
        pull_targets = []
        selected_modules = []
        if config_pk and device_ids:
            peat_config = PeatConfig.objects.get(pk=config_pk)
            try:
                device_list, pull_targets, target_mode = get_selected_config_targets(
                    config_pk, device_ids
                )
            except PeatTargetSelectionError as error:
                return JsonResponse({"status": False, "message": str(error)})
        else:
            pull_targets = parse_default_targets(data.get("cidr_id"))
            device_list = pull_targets
            try:
                selected_modules = parse_default_modules(data.get("device_types"))
            except ValidationError as error:
                return JsonResponse(
                    {"status": False, "message": "\n".join(error.messages)}
                )

        if not pull_targets:
            return JsonResponse(
                {
                    "status": False,
                    "message": "Provide at least one host or CIDR target to pull.",
                }
            )

        busy_target_display_map = (
            _build_busy_target_display_map(device_list, pull_targets, target_mode)
            if config_pk and device_ids
            else {}
        )

        celery_task_id = str(uuid.uuid4())
        peat_pull_obj = PeatPull(
            name=name,
            baseline=baseline,
            devices=device_list,
            run_dir=name,
            modules=selected_modules,
            config=peat_config,
            task_id=celery_task_id,
        )
        response = {}
        lock_owner = None
        try:
            peat_pull_obj.full_clean()
            if queue_if_busy:
                peat_pull_obj.status = "waiting"
            peat_pull_obj.save()
            lock_owner = build_owner_token_for_run(peat_pull_obj)

            if queue_if_busy:
                resolved_targets = _resolve_peat_targets_for_queue(
                    pull_targets, target_mode
                )
                result = peat_pull.apply_async(
                    (
                        peat_pull_obj.pk,
                        resolved_targets,
                        url,
                        target_mode,
                        True,
                        False,
                    ),
                    task_id=celery_task_id,
                )
                response["status"] = True
                response["message"] = result.id
                response["pk"] = peat_pull_obj.pk
                response["queued_for_locks"] = True
                return JsonResponse(response)

            lock_acquisition = acquire_target_locks(
                owner=lock_owner,
                targets=pull_targets,
                target_mode=target_mode,
            )
            if not lock_acquisition.acquired:
                _delete_unscheduled_run(peat_pull_obj)
                busy_targets = _display_busy_targets(
                    lock_acquisition.busy_targets,
                    busy_target_display_map,
                )
                return JsonResponse(_busy_lock_response(busy_targets))

            result = peat_pull.apply_async(
                (peat_pull_obj.pk, lock_acquisition.targets, url, target_mode),
                task_id=celery_task_id,
            )
            response["status"] = True
            response["message"] = result.id
            response["pk"] = peat_pull_obj.pk
        except ValidationError as error:
            response["status"] = False
            response["message"] = "\n".join(error.messages)
        except PeatLockError as error:
            LOGGER.info("Failed to acquire PEAT pull locks: %s", error)
            _delete_unscheduled_run(peat_pull_obj)
            response["status"] = False
            response["message"] = str(error)
        except Exception as error:
            LOGGER.exception("Failed to queue PEAT pull")
            _release_peat_locks_safely(lock_owner)
            if peat_pull_obj.pk:
                peat_pull_obj.status = "error"
                peat_pull_obj.save(update_fields=["status"])
                peat_pull_obj._append_console_message(
                    f"Failed to queue PEAT pull task: {error}"
                )
            response["status"] = False
            response["message"] = "Unable to queue PEAT pull task."
        return JsonResponse(response)


class PeatScanView(PeatRunView):
    """
    Django handler to create a new peat scan and signal celery to start
    the scan asynchronously using the peat interface.
    """

    model = PeatScan
    template_name = "peat/peat_scan.html"

    def post(self, request):
        data = json.loads(request.body)
        config_pk = data.get("config")
        device_ids = data.get("device_ids", [])
        name = get_peat_run_name("scan", data.get("peat_run_name"))
        push = data.get("peat_run_push", False)
        intensive_scan = data.get("intensive_scan", False)
        queue_if_busy = data.get("queue_if_busy", False)
        url = None
        if push:
            response = get_database_status(request=request)
            status = json.loads(response.content)["status"]
            if not status:
                return response
            url = get_database_url(request=request)

        target_mode = "ip"
        device_list = []
        scan_targets = []
        selected_modules = []
        if config_pk and device_ids:
            try:
                device_list, scan_targets, target_mode = get_selected_config_targets(
                    config_pk, device_ids
                )
            except PeatTargetSelectionError as error:
                return JsonResponse({"status": False, "message": str(error)})
        else:
            scan_targets = parse_default_targets(data.get("cidr_id"))
            device_list = scan_targets
            try:
                selected_modules = parse_default_modules(data.get("device_types"))
            except ValidationError as error:
                return JsonResponse(
                    {"status": False, "message": "\n".join(error.messages)}
                )

        if not scan_targets:
            return JsonResponse(
                {
                    "status": False,
                    "message": "Provide at least one host or CIDR target to scan.",
                }
            )

        busy_target_display_map = (
            _build_busy_target_display_map(device_list, scan_targets, target_mode)
            if config_pk and device_ids
            else {}
        )

        celery_task_id = str(uuid.uuid4())
        peat_scan_obj = PeatScan(
            name=name,
            devices=device_list,
            run_dir=name,
            modules=selected_modules,
            task_id=celery_task_id,
            config_id=config_pk or None,
        )
        lock_owner = None
        try:
            peat_scan_obj.full_clean()
            if queue_if_busy:
                peat_scan_obj.status = "waiting"
            peat_scan_obj.save()
            lock_owner = build_owner_token_for_run(peat_scan_obj)

            if queue_if_busy:
                resolved_targets = _resolve_peat_targets_for_queue(
                    scan_targets, target_mode
                )
                result = peat_scan.apply_async(
                    (
                        peat_scan_obj.pk,
                        resolved_targets,
                        url,
                        config_pk,
                        intensive_scan,
                        target_mode,
                        True,
                        False,
                    ),
                    task_id=celery_task_id,
                )
                return JsonResponse(
                    {
                        "status": True,
                        "message": result.id,
                        "pk": peat_scan_obj.pk,
                        "queued_for_locks": True,
                    }
                )

            lock_acquisition = acquire_target_locks(
                owner=lock_owner,
                targets=scan_targets,
                target_mode=target_mode,
            )
            if not lock_acquisition.acquired:
                _delete_unscheduled_run(peat_scan_obj)
                busy_targets = _display_busy_targets(
                    lock_acquisition.busy_targets,
                    busy_target_display_map,
                )
                return JsonResponse(_busy_lock_response(busy_targets))

            result = peat_scan.apply_async(
                (
                    peat_scan_obj.pk,
                    lock_acquisition.targets,
                    url,
                    config_pk,
                    intensive_scan,
                    target_mode,
                ),
                task_id=celery_task_id,
            )
        except ValidationError as error:
            return JsonResponse(
                {"status": False, "message": "\n".join(error.messages)}
            )
        except PeatLockError as error:
            LOGGER.info("Failed to acquire PEAT scan locks: %s", error)
            _delete_unscheduled_run(peat_scan_obj)
            return JsonResponse({"status": False, "message": str(error)})
        except Exception as error:
            LOGGER.exception("Failed to queue PEAT scan")
            _release_peat_locks_safely(lock_owner)
            if peat_scan_obj.pk:
                peat_scan_obj.status = "error"
                peat_scan_obj.save(update_fields=["status"])
                peat_scan_obj._append_console_message(
                    f"Failed to queue PEAT scan task: {error}"
                )
            return JsonResponse(
                {"status": False, "message": "Unable to queue PEAT scan task."}
            )
        return JsonResponse(
            {"status": True, "message": result.id, "pk": peat_scan_obj.pk}
        )


class PeatPullDetailView(DetailView):
    """Django template to handle context and rendering details of a
    selected peat pull or scan."""

    model = PeatPull
    template_name = "peat/run_details.html"


class PeatScanDetailView(DetailView):
    """Django template to handle context and rendering details of a
    selected peat pull or scan."""

    model = PeatScan
    template_name = "peat/run_details.html"


class PeatResultsView(View):

    def get(self, request):
        """Returns json list of all folders in peat pull directory"""
        from .data_source import list_pull_datasets

        folders = [dataset["id"] for dataset in list_pull_datasets()]
        return JsonResponse(folders, safe=False)

    def post(self, request):
        """Returns status of an individual peat run"""
        try:
            data = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"message": "Invalid request body."}, status=400)

        pk = data.get("pk")
        method = data.get("method")
        if method == "pull":
            obj = get_object_or_404(PeatPull, pk=pk)
        elif method == "scan":
            obj = get_object_or_404(PeatScan, pk=pk)
        else:
            raise Http404("method is not pull or scan")
        return JsonResponse({"status": obj.status, "run_dir": obj.run_dir}, safe=False)


def _get_run_file_context(method, pk):
    if method == "pull":
        obj = get_object_or_404(PeatPull, pk=pk)
        parent_run_dir = settings.PEAT_PULL_DIR
    elif method == "scan":
        obj = get_object_or_404(PeatScan, pk=pk)
        parent_run_dir = settings.PEAT_SCAN_DIR
    else:
        raise Http404("method is not pull or scan")

    if not obj.run_dir:
        raise Http404("Run files are not available yet.")

    parent_run_dir = Path(parent_run_dir).resolve()
    root = (parent_run_dir / obj.run_dir).resolve()
    try:
        root.relative_to(parent_run_dir)
    except ValueError:
        raise Http404("Invalid run directory.")

    if not root.is_dir():
        raise Http404("Run files are not available.")
    return obj, root


@require_GET
def peat_run_file(request, method, pk):
    _, root = _get_run_file_context(method, pk)
    relative_path = request.GET.get("path", "")
    if not relative_path:
        raise Http404("File path is required.")

    file_path = (root / relative_path).resolve()
    try:
        file_path.relative_to(root)
    except ValueError:
        raise Http404("Invalid file path.")

    if not file_path.is_file() or file_path.is_symlink():
        raise Http404("File is not available.")

    content_type, _ = mimetypes.guess_type(file_path.name)
    as_attachment = request.GET.get("download") == "1"
    viewable_suffixes = {
        ".conf",
        ".csv",
        ".ini",
        ".json",
        ".jsonl",
        ".log",
        ".md",
        ".txt",
        ".yaml",
        ".yml",
    }
    if not as_attachment and file_path.suffix.lower() not in viewable_suffixes:
        content_type = "application/octet-stream"

    fallback_content_type = "application/octet-stream" if as_attachment else "text/plain"
    response = FileResponse(
        file_path.open("rb"),
        as_attachment=as_attachment,
        filename=file_path.name,
        content_type=content_type or fallback_content_type,
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_POST
def peat_run_stop(request):
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"message": "Invalid request body."}, status=400)

    instance = data.get("pk", "")
    pull_or_scan = data.get("pull_or_scan", "")
    if pull_or_scan == "pull":
        obj = get_object_or_404(PeatPull, pk=instance)
    elif pull_or_scan == "scan":
        obj = get_object_or_404(PeatScan, pk=instance)
    else:
        raise Http404("method is not pull or scan")
    obj.stop()
    obj.refresh_from_db(fields=["status"])
    return JsonResponse({"message": "success", "status": obj.status}, status=200)


@require_POST
def peat_run_download(request):
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"message": "Invalid request body."}, status=400)

    instance = data.get("pk", "")
    pull_or_scan = data.get("pull_or_scan", "")
    if pull_or_scan == "pull":
        obj = get_object_or_404(PeatPull, pk=instance)
        parent_run_dir = settings.PEAT_PULL_DIR
    elif pull_or_scan == "scan":
        obj = get_object_or_404(PeatScan, pk=instance)
        parent_run_dir = settings.PEAT_SCAN_DIR
    else:
        raise Http404("method is not pull or scan")
    run_dir = obj.run_dir
    if not run_dir:
        return JsonResponse(
            {"message": "Run files are not available yet."}, status=404
        )

    parent_run_dir = Path(parent_run_dir).resolve()
    folder_path = (parent_run_dir / run_dir).resolve()
    try:
        folder_path.relative_to(parent_run_dir)
    except ValueError:
        return JsonResponse({"message": "Invalid run directory."}, status=400)

    if not folder_path.is_dir():
        return JsonResponse(
            {"message": "Run files are not available."}, status=404
        )

    run_files = []
    for file_path in folder_path.rglob("*"):
        if not file_path.is_file() or file_path.is_symlink():
            continue
        try:
            file_path.resolve().relative_to(folder_path)
        except ValueError:
            continue
        run_files.append(file_path)
    if not run_files:
        return JsonResponse(
            {"message": "Run files are not available."}, status=404
        )

    download_name = clean_directory_name(run_dir) or "peat-run"
    zip_filename = f"{download_name}.zip"
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in run_files:
            zip_file.write(file_path, file_path.relative_to(folder_path))

    # Set the buffer position to the beginning
    zip_buffer.seek(0)
    response = HttpResponse(zip_buffer, content_type="application/zip")
    response["Content-Disposition"] = f"attachment; filename={zip_filename}"
    return response
