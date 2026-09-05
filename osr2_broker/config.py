from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app_support import state_files
from app_support.config_reader import read_json_config, require_path, require_typed, resolve_path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_DIR / "osr2_broker_config.json"

# Evolver, whose launcher this tray runs when it finds Evolver gone (see
# osr2_broker/peer_watch.py). Relative to this repo, because the pair is a
# pair of sibling checkouts; a machine with no Evolver beside the broker
# leaves this pointing at nothing, which is how the watch turns itself off.
DEFAULT_EVOLVER_LAUNCHER = "../evolver/launch_evolver.vbs"


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
    tcode_udp_port: int
    evolver_launcher: Path

    @property
    def genau_mode_file(self) -> Path:
        return self.state_dir / state_files.GENAU_MODE

    @property
    def genau_enabled_file(self) -> Path:
        return self.state_dir / state_files.GENAU_ENABLED

    @property
    def broker_cmd_file(self) -> Path:
        return self.state_dir / state_files.BROKER_CMD

    @property
    def broker_heartbeat_file(self) -> Path:
        return self.state_dir / state_files.BROKER_HEARTBEAT

    @property
    def osr2_serial_rx_file(self) -> Path:
        return self.state_dir / state_files.OSR2_SERIAL_RX

    @property
    def osr2_serial_tx_file(self) -> Path:
        return self.state_dir / state_files.OSR2_SERIAL_TX

    @property
    def osr2_idle_state_file(self) -> Path:
        return self.state_dir / "osr2_idle_state.txt"

    def log_file(self, name: str) -> Path:
        return self.state_dir / f"{name}.log"


def load_config(config_path: str | Path | None = None) -> BrokerConfig:
    # Every required key is asked for by name, so a config short of one says
    # which, and in which file, rather than a bare KeyError from a launcher
    # with no console to raise into.
    path, raw = read_json_config(Path(config_path) if config_path else DEFAULT_CONFIG_PATH,
                                 default_dir=PROJECT_DIR)
    project_dir = path.parent

    return BrokerConfig(
        config_path=path,
        project_dir=project_dir,
        state_dir=require_path(raw, "state_dir", path, base=project_dir),
        virtual_port=require_typed(raw, "virtual_port", path, cast=str),
        real_port=require_typed(raw, "real_port", path, cast=str),
        baud=require_typed(raw, "baud", path, cast=int),
        udp_host=require_typed(raw, "udp_host", path, cast=str),
        udp_port=require_typed(raw, "udp_port", path, cast=int),
        auto_stale_timeout=require_typed(raw, "auto_stale_timeout", path, cast=float),
        idle_minutes=float(raw.get("idle_minutes", 15.0)),
        mfp_config_path=resolve_path(project_dir, raw.get("mfp_config_path", "")),
        tcode_udp_port=int(raw.get("tcode_udp_port", 50557)),
        evolver_launcher=resolve_path(
            project_dir, raw.get("evolver_launcher", DEFAULT_EVOLVER_LAUNCHER)),
    )
