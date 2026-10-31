from parseus.datastore.peat import PeatDocumentData
from parseus.interfaces import ot_device as OT
from parseus.preprocessors.peat_normalize import (
    as_list,
    file_identity_values,
    normalize_firmware_logs,
    normalize_io_modules,
    normalize_process_memory,
    normalize_services,
)


def peat_device_transform(docs: PeatDocumentData, **_):
    """
    Transforms PEAT device documents into a set of detected device IDs and timestamps.
    """
    devices = set()
    for doc in docs:
        devices.add((doc.device_id, doc.timestamp))
    return devices


def peat_file_transform(docs: PeatDocumentData, **_):
    """
    Transforms PEAT device documents into device file identities.
    returns: {device_id: (timestamp, set(files))}
    """
    files = {}
    for doc in docs:
        data = doc.summary
        related_files = set(
            file_identity_values((data.get("related") or {}).get("files"))
        )
        related_files.update(file_identity_values(data.get("files")))
        if related_files:
            files[doc.device_id] = (doc.timestamp, related_files)
    return files


def peat_service_transform(docs: PeatDocumentData, **_):
    """
    Transforms PEAT device documents into service records per device.
    """
    services = {}
    for doc in docs:
        data = doc.summary
        if "service" in data:
            services[doc.device_id] = (
                doc.timestamp,
                normalize_services(data["service"]),
            )
    return services


def peat_process_transform(docs: PeatDocumentData, **_):
    """Transforms PEAT memory records into process records per device."""
    processes = {}
    for doc in docs:
        processes[doc.device_id] = (
            doc.timestamp,
            normalize_process_memory(doc.summary),
        )
    return processes


def peat_io_transform(docs: PeatDocumentData, **_):
    """Transforms PEAT IO records into modules per device."""
    io = {}
    for doc in docs:
        io[doc.device_id] = (
            doc.timestamp,
            normalize_io_modules(doc.summary.get("io")),
        )
    return io


def peat_event_transform(docs: PeatDocumentData, **_):
    """Transforms PEAT event records into event logs per device."""
    events = {}
    for doc in docs:
        events[doc.device_id] = (
            doc.timestamp,
            {"EventLogs": as_list(doc.summary.get("event"))},
        )
    return events


def peat_firmware_transform(docs: PeatDocumentData, **_):
    """Transforms PEAT firmware fields into firmware records per device."""
    firmware_updates = {}
    for doc in docs:
        firmware_updates[doc.device_id] = (
            doc.timestamp,
            normalize_firmware_logs(doc.summary),
        )
    return firmware_updates


def peat_logic_transform(docs: PeatDocumentData, **_):
    """Transforms PEAT logic records into logic data per device."""
    logic = {}
    for doc in docs:
        if "logic" in doc.summary:
            logic[doc.device_id] = (doc.timestamp, doc.summary["logic"])
    return logic


def ot_transform(data, **kwargs):
    peat_set = set()
    for record in data:
        device = OT.OTDevice(record)
        peat_set.add(device)
    return peat_set
