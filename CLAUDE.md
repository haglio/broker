# osr2_broker — Project-Specific Instructions

Shared rules are in the global `~/.claude/CLAUDE.md`. This file contains only osr2_broker-specific overrides.

## Test commands

Unit tests (run freely, no permission needed):
```bash
.venv/Scripts/python.exe -m pytest
```

No integration tests currently.

## Architecture

- Serial broker: bridges MFP (virtual COM port) ↔ OSR2 (real COM4)
- Auto-mode state machine: parses OSR2 serial output, publishes to Genau via UDP
- Idle monitor: alerts after configurable idle timeout, blocks Windows shutdown when device is on
- Tray UI: PowerShell WinForms tray icon with auto-restart

The monitor runs on a dedicated daemon thread with its own Win32 message pump (ShutdownGuard). The broker's serial forwarding runs on separate daemon threads. Main thread manages the session retry loop.

## Config

`osr2_broker_config.json` — flat JSON, one dataclass. State files are derived from `state_dir` (currently shared with fun_time's state directory).

## Relationship to fun_time

No Python import dependency. Communication is file-based IPC (heartbeat, activity timestamps, command files) + process management via PowerShell. The fun_time orchestrator detects and starts the broker as a sibling project.
