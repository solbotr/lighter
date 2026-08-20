from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class KillSwitchState:
    active: bool
    reason: str
    changed_at: str


class KillSwitch:
    def __init__(self, path: str | os.PathLike[str] = "runtime/kill_switch.json") -> None:
        self.path = Path(path)

    def state(self) -> KillSwitchState:
        if not self.path.exists():
            return KillSwitchState(False, "", "")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return KillSwitchState(bool(payload["active"]), str(payload.get("reason", "")), str(payload.get("changed_at", "")))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RuntimeError("kill-switch state is unreadable; refusing execution") from exc

    def activate(self, reason: str) -> KillSwitchState:
        if not reason.strip():
            raise ValueError("kill-switch reason is required")
        return self._write(True, reason)

    def clear(self, approval: str) -> KillSwitchState:
        if not approval.strip():
            raise ValueError("operator approval is required to clear kill switch")
        return self._write(False, f"cleared:{approval}")

    def _write(self, active: bool, reason: str) -> KillSwitchState:
        state = KillSwitchState(active, reason, datetime.now(timezone.utc).isoformat())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state.__dict__, sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)
        return state
