from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_DIR / "osr2_broker_config.json"


@dataclass(frozen=True)
class BrokerConfig:
    config_path: Path
    project_dir: Path
    state_dir: Path
    virtual_port: str
    real_port: str
    baud: int
    udp_host: str
    udp_port: int
    auto_stale_timeout: float
    idle_minutes: float
    mfp_config_path: Path

    @property
    def genau_mode_file(self) -> Path:
        return self.state_dir / "genau_mode.txt"

    @property
    def genau_enabled_file(self) -> Path:
        return self.state_dir / "genau_enabled.txt"

    @property
    def broker_cmd_file(self) -> Path:
        return self.state_dir / "broker_cmd.txt"

    @property
    def broker_heartbeat_file(self) -> Path:
        return self.state_dir / "broker_heartbeat.txt"

    @property
    def osr2_serial_rx_file(self) -> Path:
        return self.state_dir / "osr2_serial_rx.txt"

    @property
    def osr2_serial_tx_file(self) -> Path:
        return self.state_dir / "osr2_serial_tx.txt"

    def log_file(self, name: str) -> Path:
        return self.state_dir / f"{name}.log"


def _resolve_path(base: Path, raw: str) -> Path:
    p = Path(raw)
    if p.is_absolute():
        return p
    return (base / p).resolve()


def load_config(config_path: str | Path | None = None) -> BrokerConfig:
    path = Path(config_path).expanduser() if config_path else DEFAULT_CONFIG_PATH
    if not path.is_absolute():
        path = (PROJECT_DIR / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as fp:
        raw: dict = json.load(fp)

    project_dir = path.parent

    return BrokerConfig(
        config_path=path,
        project_dir=project_dir,
        state_dir=_resolve_path(project_dir, raw["state_dir"]),
        virtual_port=str(raw["virtual_port"]),
        real_port=str(raw["real_port"]),
        baud=int(raw["baud"]),
        udp_host=str(raw["udp_host"]),
        udp_port=int(raw["udp_port"]),
        auto_stale_timeout=float(raw["auto_stale_timeout"]),
        idle_minutes=float(raw.get("idle_minutes", 15.0)),
        mfp_config_path=_resolve_path(project_dir, raw.get("mfp_config_path", "")),
    )
