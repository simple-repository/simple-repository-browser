import datetime
import logging

from simple_repository import SimpleRepository


def create_table(connection):
    con = connection
    with con as cursor:
        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS projects
            (canonical_name text unique, preferred_name text, summary text, release_date timestamp, release_version text)
            ''',
        )


def insert_if_missing(connection, canonical_name, preferred_name):
    with connection as cursor:
        cursor.execute(
            "INSERT OR IGNORE into projects(canonical_name, preferred_name) values (?, ?)",
            (canonical_name, preferred_name),
        )


def remove_if_found(connection, canonical_name):
    with connection as cursor:
        cursor.execute('DELETE FROM projects where canonical_name = ?;', (canonical_name,))


def update_summary(conn, name: str, summary: str, release_date: datetime.datetime, release_version: str):
    with conn as cursor:
        cursor.execute(
            '''
        UPDATE projects
        SET summary = ?, release_date = ?, release_version = ?
        WHERE canonical_name == ?;
        ''', (summary, release_date, release_version, name),
        )


async def fully_populate_db(connection, repository: SimpleRepository):
    con = connection
    logging.info('Fetching names from repository')
    project_list = await repository.get_project_list()
    project_names = [
        (project.normalized_name, project.name) for project in project_list.projects
    ]
    logging.info('Inserting all new names (if any)')
    with con as cursor:
        for canonical_name, name in project_names:
            cursor.execute(
                "INSERT OR IGNORE into projects(canonical_name, preferred_name) values (?, ?)",
                (canonical_name, name),
            )

    with con as cursor:
        db_canonical_names = {row[0] for row in cursor.execute("SELECT canonical_name FROM projects").fetchall()}

    index_canonical_names = {normed_name for normed_name, _ in project_names}

    if not index_canonical_names:
        logging.warning("No names found in the repository. Not removing from the database, as this is likely a problem with the repository.")
        return

    names_in_db_no_longer_in_index = db_canonical_names - index_canonical_names
    if names_in_db_no_longer_in_index:
        logging.warning(
            f'Removing the following { len(names_in_db_no_longer_in_index) } names from the database:\n   '
            "\n   ".join(list(names_in_db_no_longer_in_index)[:2000]) + "\n",
        )
    with con as cursor:
        for name in names_in_db_no_longer_in_index:
            cursor.execute(
                '''
                DELETE FROM projects
                WHERE canonical_name == ?;
                ''',
                (name,),
            )
    logging.info('DB synchronised with repository')
