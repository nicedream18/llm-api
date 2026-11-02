"""Execution identity used to fence every knowledge task publication."""
from dataclasses import dataclass, field
from threading import Event


class LostTaskLease(RuntimeError):
    pass


@dataclass
class TaskLease:
    worker_id: str
    generation: int
    cancelled: Event = field(default_factory=Event)

    def check(self) -> None:
        if self.cancelled.is_set():
            raise LostTaskLease("Knowledge task lease lost")
