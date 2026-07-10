import datetime
import logging

from simple_repository import SimpleRepository


def create_table(connection):
    con = connection
    with con as cursor:
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS projects
            (canonical_name text unique, preferred_name text, summary text,
             release_date timestamp, release_version text, metadata_json text)
            """,
        )
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS dependencies_idx (
                canonical_name TEXT NOT NULL,
                dep_canonical_name TEXT NOT NULL,
                extra TEXT,
                specifier TEXT,
                marker TEXT
            )""",
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_deps_dep "
            "ON dependencies_idx(dep_canonical_name)",
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_deps_dep_extra "
            "ON dependencies_idx(dep_canonical_name, extra)",
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_deps_owner "
            "ON dependencies_idx(canonical_name)",
        )
        cursor.execute(
            """CREATE TRIGGER IF NOT EXISTS projects_deps_ai
               AFTER INSERT ON projects
               WHEN NEW.metadata_json IS NOT NULL
               BEGIN
                 INSERT INTO dependencies_idx(
                     canonical_name, dep_canonical_name, extra, specifier, marker
                 )
                 SELECT NEW.canonical_name,
                        json_extract(value, '$.name'),
                        json_extract(value, '$.extra'),
                        json_extract(value, '$.specifier'),
                        json_extract(value, '$.marker')
                 FROM json_each(
                     json_extract(NEW.metadata_json, '$.requires_dist')
                 );
               END;""",
        )
        cursor.execute(
            """CREATE TRIGGER IF NOT EXISTS projects_deps_au
               AFTER UPDATE OF metadata_json ON projects
               BEGIN
                 DELETE FROM dependencies_idx
                 WHERE canonical_name = NEW.canonical_name;
                 INSERT INTO dependencies_idx(
                     canonical_name, dep_canonical_name, extra, specifier, marker
                 )
                 SELECT NEW.canonical_name,
                        json_extract(value, '$.name'),
                        json_extract(value, '$.extra'),
                        json_extract(value, '$.specifier'),
                        json_extract(value, '$.marker')
                 FROM json_each(
                     json_extract(
                         COALESCE(NEW.metadata_json, '{"requires_dist":[]}'),
                         '$.requires_dist'
                     )
                 );
               END;""",
        )
        cursor.execute(
            """CREATE TRIGGER IF NOT EXISTS projects_deps_ad
               AFTER DELETE ON projects
               BEGIN
                 DELETE FROM dependencies_idx
                 WHERE canonical_name = OLD.canonical_name;
               END;""",
        )


# Bump when adding a migration step. Each step in `migrate` is guarded by
# `if version < N` and cumulatively advances `PRAGMA user_version`.
SCHEMA_VERSION = 2


def migrate(connection):
    """Advance the DB to SCHEMA_VERSION via PRAGMA user_version. Idempotent."""
    with connection as cursor:
        (version,) = cursor.execute("PRAGMA user_version").fetchone()
        if version < 1:
            # v1: introduce projects.metadata_json for pre-existing DBs.
            # (Fresh DBs get the column via CREATE TABLE below.)
            tables = {
                row[0]
                for row in cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "projects" in tables:
                cols = {
                    row[1]
                    for row in cursor.execute("PRAGMA table_info(projects)").fetchall()
                }
                if "metadata_json" not in cols:
                    cursor.execute("ALTER TABLE projects ADD COLUMN metadata_json text")
        if version < 2:
            # v2: metadata_json shape gained `source` and `project_urls`.
            # Null the column so the crawler backfill / next reindex refills it
            # against the new shape. Triggers cascade the delete into
            # dependencies_idx automatically.
            tables = {
                row[0]
                for row in cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "projects" in tables:
                cursor.execute("UPDATE projects SET metadata_json = NULL")
        cursor.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    create_table(connection)


def insert_if_missing(connection, canonical_name, preferred_name):
    with connection as cursor:
        cursor.execute(
            "INSERT OR IGNORE into projects(canonical_name, preferred_name) values (?, ?)",
            (canonical_name, preferred_name),
        )


def remove_if_found(connection, canonical_name):
    with connection as cursor:
        cursor.execute(
            "DELETE FROM projects where canonical_name = ?;", (canonical_name,)
        )


def update_summary(
    conn, name: str, summary: str, release_date: datetime.datetime, release_version: str
):
    # Strip timezone info before storing in SQLite to avoid converter issues.
    # We always store naive datetimes which represent UTC.
    if release_date.tzinfo is not None:
        release_date = release_date.replace(tzinfo=None)

    with conn as cursor:
        cursor.execute(
            """
        UPDATE projects
        SET summary = ?, release_date = ?, release_version = ?
        WHERE canonical_name == ?;
        """,
            (summary, release_date, release_version, name),
        )


def update_metadata(conn, name: str, metadata_json: str) -> None:
    with conn as cursor:
        cursor.execute(
            "UPDATE projects SET metadata_json = ? WHERE canonical_name = ?",
            (metadata_json, name),
        )


async def fully_populate_db(connection, repository: SimpleRepository):
    con = connection
    logging.info("Fetching names from repository")
    project_list = await repository.get_project_list()
    project_names = [
        (project.normalized_name, project.name) for project in project_list.projects
    ]
    logging.info("Inserting all new names (if any)")
    with con as cursor:
        for canonical_name, name in project_names:
            cursor.execute(
                "INSERT OR IGNORE into projects(canonical_name, preferred_name) values (?, ?)",
                (canonical_name, name),
            )

    with con as cursor:
        db_canonical_names = {
            row[0]
            for row in cursor.execute("SELECT canonical_name FROM projects").fetchall()
        }

    index_canonical_names = {normed_name for normed_name, _ in project_names}

    if not index_canonical_names:
        logging.warning(
            "No names found in the repository. Not removing from the database, as this is likely a problem with the repository."
        )
        return

    names_in_db_no_longer_in_index = db_canonical_names - index_canonical_names
    if names_in_db_no_longer_in_index:
        logging.warning(
            f"Removing the following {len(names_in_db_no_longer_in_index)} names from the database:\n   "
            "\n   ".join(list(names_in_db_no_longer_in_index)[:2000])
            + "\n",
        )
    with con as cursor:
        for name in names_in_db_no_longer_in_index:
            cursor.execute(
                """
                DELETE FROM projects
                WHERE canonical_name == ?;
                """,
                (name,),
            )
    logging.info("DB synchronised with repository")
