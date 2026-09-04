from __future__ import annotations

import json
import re
from pathlib import Path

RE_COM0COM_PORT = re.compile(r"COM0COM\\PORT\\(CNC[AB])(\d+)", re.IGNORECASE)


def iter_serial_ports():
    try:
        from serial.tools import list_ports
    except Exception:
        return []
    return list(list_ports.comports())


def _read_mfp_config_payload(mfp_config_path: Path) -> dict | None:
    """Parsed MFP config; ``{}`` when there is no file, ``None`` when unreadable.

    ``None`` means "hands off". The file is there but we could not understand
    it -- most likely we caught MFP mid-write -- so anything we rewrite from
    what we parsed would drop every setting we failed to read.
    """
    if not mfp_config_path.exists():
        return {}
    try:
        payload = json.loads(mfp_config_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _iter_output_target_items(payload: dict):
    output_target = payload.get("OutputTarget")
    if not isinstance(output_target, dict):
        return
    items = output_target.get("Items")
    if not isinstance(items, list):
        return
    for item in items:
        if isinstance(item, dict):
            yield item


def _write_mfp_config_payload(mfp_config_path: Path, payload: dict) -> None:
    mfp_config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_mfp_selected_serial_port(mfp_config_path: Path) -> str | None:
    """The port MFP is configured to use, as a real string.

    Read through the JSON parser, never off the raw text: on disk MFP escapes
    the backslashes in ``COM0COM\\PORT\\CNCA1``, and a raw-text read hands back
    the doubled form, which matches no live port and makes every start declare
    a perfectly good config stale.
    """
    for item in _iter_output_target_items(_read_mfp_config_payload(mfp_config_path) or {}):
        selected = item.get("SelectedSerialPort")
        if isinstance(selected, str) and selected:
            return selected
    return None


def _serial_output_target(payload: dict) -> dict | None:
    """The config entry holding the serial port, or None if there is none.

    MFP keeps one entry per output target, so this has to pick the same entry
    ``read_mfp_selected_serial_port`` reads back -- otherwise the two disagree
    forever and every broker start rewrites the file.
    """
    items = list(_iter_output_target_items(payload))
    for item in items:
        if "SelectedSerialPort" in item:
            return item
    return items[0] if items else None


def write_mfp_selected_serial_port(mfp_config_path: Path, selected_port: str) -> bool:
    """Point MFP at ``selected_port``; False if the config was left untouched."""
    payload = _read_mfp_config_payload(mfp_config_path)
    target = _serial_output_target(payload) if payload is not None else None
    if target is None:
        return False
    target["SelectedSerialPort"] = selected_port
    _write_mfp_config_payload(mfp_config_path, payload)
    return True


def collect_com0com_ports() -> dict[str, tuple[str, str]]:
    ports: dict[str, tuple[str, str]] = {}
    for port in iter_serial_ports():
        device = getattr(port, "device", None)
        if not device:
            continue
        desc = str(getattr(port, "description", "") or "")
        hwid = str(getattr(port, "hwid", "") or "")
        if "com0com" not in desc.lower() and "COM0COM\\PORT\\" not in hwid.upper():
            continue
        ports[str(device).upper()] = (desc, hwid)
    return ports


def resolve_virtual_port(mfp_config_path: Path, configured_port: str, logger) -> str:
    normalized = configured_port.upper()
    com0com_ports = collect_com0com_ports()
    if normalized in com0com_ports:
        return configured_port

    if not com0com_ports:
        logger.warning("Configured virtual port %s is missing and no com0com ports were detected", configured_port)
        return configured_port

    mfp_selected = read_mfp_selected_serial_port(mfp_config_path)
    if mfp_selected:
        match = RE_COM0COM_PORT.search(mfp_selected)
        if match:
            expected_role = "CNCB" if match.group(1).upper() == "CNCA" else "CNCA"
            expected_index = match.group(2)
            for device, (_desc, hwid) in com0com_ports.items():
                hwid_match = RE_COM0COM_PORT.search(hwid)
                if hwid_match and hwid_match.group(1).upper() == expected_role and hwid_match.group(2) == expected_index:
                    logger.warning(
                        "Configured virtual port %s is missing; using %s inferred from MFP serial port %s",
                        configured_port,
                        device,
                        mfp_selected,
                    )
                    return device

    cncb_devices: list[str] = []
    for device, (_desc, hwid) in com0com_ports.items():
        hwid_match = RE_COM0COM_PORT.search(hwid)
        if hwid_match and hwid_match.group(1).upper() == "CNCB":
            cncb_devices.append(device)

    if len(cncb_devices) == 1:
        logger.warning(
            "Configured virtual port %s is missing; using sole detected com0com broker-side port %s",
            configured_port,
            cncb_devices[0],
        )
        return cncb_devices[0]

    logger.warning(
        "Configured virtual port %s is missing; detected com0com ports=%s",
        configured_port,
        ", ".join(sorted(com0com_ports)),
    )
    return configured_port


def resolve_mfp_serial_port(mfp_config_path: Path, virtual_port: str, logger) -> str | None:
    selected_port = read_mfp_selected_serial_port(mfp_config_path)
    com0com_ports = collect_com0com_ports()

    selected_match = RE_COM0COM_PORT.search(selected_port or "")
    if selected_match:
        selected_role = selected_match.group(1).upper()
        selected_index = selected_match.group(2)
        for _device, (_desc, hwid) in com0com_ports.items():
            hwid_match = RE_COM0COM_PORT.search(hwid)
            if hwid_match and hwid_match.group(1).upper() == selected_role and hwid_match.group(2) == selected_index:
                return selected_port

    broker_device = resolve_virtual_port(mfp_config_path, virtual_port, logger).upper()
    broker_entry = com0com_ports.get(broker_device)
    if broker_entry is not None:
        broker_hwid = broker_entry[1]
        broker_match = RE_COM0COM_PORT.search(broker_hwid)
        if broker_match:
            desired_role = "CNCA" if broker_match.group(1).upper() == "CNCB" else "CNCB"
            desired_index = broker_match.group(2)
            for _device, (_desc, hwid) in com0com_ports.items():
                hwid_match = RE_COM0COM_PORT.search(hwid)
                if hwid_match and hwid_match.group(1).upper() == desired_role and hwid_match.group(2) == desired_index:
                    logger.warning(
                        "MFP serial port %s is stale; using detected %s to match broker port %s",
                        selected_port,
                        hwid,
                        broker_device,
                    )
                    return hwid

    cnca_hwids: list[str] = []
    for _device, (_desc, hwid) in com0com_ports.items():
        hwid_match = RE_COM0COM_PORT.search(hwid)
        if hwid_match and hwid_match.group(1).upper() == "CNCA":
            cnca_hwids.append(hwid)
    if len(cnca_hwids) == 1:
        logger.warning("MFP serial port %s is stale; using sole detected com0com MFP-side port %s", selected_port, cnca_hwids[0])
        return cnca_hwids[0]

    return selected_port


def ensure_mfp_serial_port(mfp_config_path: Path, virtual_port: str, logger) -> str | None:
    resolved = resolve_mfp_serial_port(mfp_config_path, virtual_port, logger)
    if not resolved:
        return None
    current = read_mfp_selected_serial_port(mfp_config_path)
    if current == resolved:
        return current
    if not write_mfp_selected_serial_port(mfp_config_path, resolved):
        logger.warning("Could not point MFP at %s; left %s alone", resolved, mfp_config_path)
        return current
    logger.info("Updated MFP selected serial port to %s", resolved)
    return resolved
