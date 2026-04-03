from __future__ import annotations

import re
import json
from pathlib import Path


RE_COM0COM_PORT = re.compile(r"COM0COM\\PORT\\(CNC[AB])(\d+)", re.IGNORECASE)


def iter_serial_ports():
    try:
        from serial.tools import list_ports
    except Exception:
        return []
    return list(list_ports.comports())


def _read_mfp_config_payload(mfp_config_path: Path) -> dict:
    if not mfp_config_path.exists():
        return {}
    try:
        return json.loads(mfp_config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_mfp_config_payload(mfp_config_path: Path, payload: dict) -> None:
    mfp_config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_mfp_selected_serial_port(mfp_config_path: Path) -> str | None:
    try:
        if not mfp_config_path.exists():
            return None
        text = mfp_config_path.read_text(encoding="utf-8")
    except Exception:
        return None

    match = re.search(r'"SelectedSerialPort"\s*:\s*"([^"]+)"', text)
    if not match:
        return None
    return match.group(1)


def write_mfp_selected_serial_port(mfp_config_path: Path, selected_port: str) -> None:
    payload = _read_mfp_config_payload(mfp_config_path)
    output_target = payload.setdefault("OutputTarget", {})
    items = output_target.setdefault("Items", [])
    if not items:
        items.append({})
    first_item = items[0]
    if not isinstance(first_item, dict):
        first_item = {}
        items[0] = first_item
    first_item["SelectedSerialPort"] = selected_port
    _write_mfp_config_payload(mfp_config_path, payload)


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
    write_mfp_selected_serial_port(mfp_config_path, resolved)
    logger.info("Updated MFP selected serial port to %s", resolved)
    return resolved
