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
- Tray UI: PyQt6 tray icon (`osr2_broker/tray.py`), dark-themed via shared_ui, which supervises and auto-restarts the broker

The monitor runs on a dedicated daemon thread with its own Win32 message pump (ShutdownGuard). The broker's serial forwarding runs on separate daemon threads. Main thread manages the session retry loop.

## Config

`osr2_broker_config.json` — flat JSON, one dataclass. State files are derived from `state_dir` (currently shared with fun_time's state directory).

## Relationship to fun_time

No Python import dependency. Communication is file-based IPC (heartbeat, activity timestamps, command files) + process management via PowerShell. The fun_time orchestrator detects and starts the broker as a sibling project.

## Test fixtures must be fabricated, never copied from the real library

Every fixture value that stands in for library data — a video title, a filename,
a performer or studio name, prompt text — must be **invented**. Never paste a
real one out of the media library to make a test feel realistic.

This is not a style note. It is the single thing that has actually leaked private
data into these repos: an agent writing a test reached for a real filename or
performer name because it was handy, and it rode into a public commit. Nothing in
the app's *design* pulls library text into source — the library lives outside
every repo, read at runtime through the git-ignored overlays — so this habit is
the only remaining path for a real name to get committed, and the only thing
stopping it is you following this rule.

Do not lean on the sanitize guard to catch it. `tools/sanitize_guard.py` fails
the suite when a **known** blocked term appears in the tracked tree, but a brand-
new performer name it has never seen passes every check and lands. The guard is a
backstop for names already known; it cannot see the next one.

So fabricate fully. Use `Jane Doe`, `Example Studio`, `scene one`, the
`alpha`/`beta`/`gamma` act placeholders the committed `content.example.json`
already uses. The near miss that still counts: taking a real filename and
changing a character or two — it is still that clip, still that performer. Make
it up from scratch, don't lightly edit a real one.
