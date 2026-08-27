"""Build structural-index and compass sidecars for a stored graph."""

from pathlib import Path

import engine


def build_indexes(db_path: Path) -> None:
    engine.reset_connection()
    conn = engine.get_connection(str(db_path.resolve()))
    structural = engine.get_structural_index(conn)
    _ = engine.get_compass(conn, structural)


run_post_generation_indexing = build_indexes
