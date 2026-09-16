import hashlib
from pathlib import Path

from .clickhouse import ClickHouseRepository


def migrate(repository: ClickHouseRepository) -> list[str]:
    repository.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version String, checksum String) ENGINE = ReplacingMergeTree ORDER BY version"
    )
    applied = {
        row["version"]: row["checksum"]
        for row in repository.rows("SELECT version, checksum FROM schema_migrations FINAL")
    }
    completed = []
    for path in sorted(Path(__file__).with_name("migrations").glob("*.sql")):
        sql = path.read_text()
        checksum = hashlib.sha256(sql.encode()).hexdigest()
        if path.stem in applied:
            if applied[path.stem] != checksum:
                raise ValueError(f"Applied ClickHouse migration changed: {path.stem}")
            continue
        for statement in sql.split(";"):
            if statement.strip():
                repository.execute(statement)
        repository.execute(
            "INSERT INTO schema_migrations VALUES ({version:String}, {checksum:String})",
            {"version": path.stem, "checksum": checksum},
        )
        completed.append(path.stem)
    return completed
