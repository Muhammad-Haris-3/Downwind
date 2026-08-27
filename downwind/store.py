"""Append-only newline-delimited JSON storage, partitioned by UTC day.

Nothing here ever opens a file in a mode that can truncate. The only write
operation is append. Rewriting history requires deleting a file by hand, which
git would record.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator


class Store:
    """A partitioned append-only NDJSON store rooted at ``base``."""

    def __init__(self, base: Path | str) -> None:
        self.base = Path(base)

    def partition(self, stream: str, when: datetime) -> Path:
        """Path of the file holding ``stream`` records for ``when``'s UTC day."""
        return self.base / stream / f"{when.strftime('%Y-%m-%d')}.ndjson"

    def append(self, stream: str, when: datetime, records: Iterable[dict[str, Any]]) -> int:
        """Append ``records`` to the partition for ``when``. Returns the count.

        Each record is written as one line. The file is opened in append mode
        and flushed to disk before returning, so a process killed mid-run leaves
        whole lines behind rather than a truncated file.
        """
        path = self.partition(stream, when)
        path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
                fh.write("\n")
                written += 1
            fh.flush()
            os.fsync(fh.fileno())
        return written

    def read(self, stream: str, when: datetime) -> Iterator[dict[str, Any]]:
        """Yield every record in one partition, skipping blank lines."""
        path = self.partition(stream, when)
        if not path.exists():
            return
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def count(self, stream: str, when: datetime) -> int:
        return sum(1 for _ in self.read(stream, when))
