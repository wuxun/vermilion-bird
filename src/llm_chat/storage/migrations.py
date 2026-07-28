"""SQLite schema 迁移描述、报告和错误类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional


MigrationCallable = Callable[[object], None]


@dataclass(frozen=True)
class SchemaMigration:
    version: int
    name: str
    apply: MigrationCallable


@dataclass
class MigrationReport:
    from_version: int
    to_version: int
    applied: List[int] = field(default_factory=list)
    backup_path: Optional[str] = None


class SchemaMigrationError(RuntimeError):
    def __init__(
        self,
        *,
        version: int,
        name: str,
        cause: Exception,
        backup_path: Optional[str],
    ):
        self.version = version
        self.name = name
        self.cause = cause
        self.backup_path = backup_path
        backup_note = f"; backup restored from {backup_path}" if backup_path else ""
        super().__init__(
            f"database migration {version} ({name}) failed: {cause}{backup_note}"
        )
