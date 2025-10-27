from __future__ import annotations

import sys
from pathlib import Path

# Ensure `src` is on sys.path for imports
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bybit_tax_app.db import init_db, get_session
from bybit_tax_app.models import TaskResult


def main() -> None:
    init_db()
    with get_session() as session:
        tr = TaskResult(task_name="smoke_test", status="completed", message="ok")
        session.add(tr)
    with get_session() as session:
        count = session.query(TaskResult).count()
        last = session.query(TaskResult).order_by(TaskResult.id.desc()).first()
    print({"task_results_count": count, "last_message": last.message if last else None})


if __name__ == "__main__":
    main()
