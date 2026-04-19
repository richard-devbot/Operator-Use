from __future__ import annotations

import asyncio
from datetime import datetime


class Process:
    def __init__(self, session_id: str, cmd: str, process: asyncio.subprocess.Process):
        self.session_id = session_id
        self.cmd = cmd
        self.process = process
        self.started_at = datetime.now()
        self.output: list[str] = []
        self._reader: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        return self.process.returncode is None

    @property
    def exit_code(self) -> int | None:
        return self.process.returncode

    def tail(self, n: int = 20) -> str:
        return "\n".join(self.output[-n:])

    def full_log(self) -> str:
        return "\n".join(self.output)
