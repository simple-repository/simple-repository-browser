import asyncio
import sqlite3

from ._pypil import PackageName


def create_table(connection):
    con = connection
    with con as cursor:
        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS projects
            (canonical_name text unique, preferred_name text, summary text, description_html text)
            '''
        )


def insert_if_missing(connection, canonical_name, preferred_name):
    with connection as cursor:
        cursor.execute(
            "insert OR IGNORE into projects(canonical_name, preferred_name, summary, description_html) values (?, ?, ?, ?)",
            (canonical_name, preferred_name, '', ''),
        )


def remove_if_found(connection, canonical_name):
    with connection as cursor:
        cursor.execute('DELETE FROM projects where canonical_name = ?;', (canonical_name,)).fetchone()


def update_summary(conn, name, summary):
    with conn as cursor:
        cursor.execute('''
        UPDATE projects
        SET summary = ?
        WHERE canonical_name == ?;
        ''', (summary, name))


async def fully_populate_db(connection, index):
    con = connection
    print('Fetching names from index')

    loop = asyncio.get_event_loop()
    non_canonical_project_names = await loop.run_in_executor(None, index.project_names)

    project_names = [(PackageName(project).normalized, project) for project in non_canonical_project_names]
    print('Inserting all new names (if any)')
    with con as cursor:
        for canonical_name, name in project_names:
            cursor.execute(
                "insert OR IGNORE into projects(canonical_name, preferred_name, summary, description_html) values (?, ?, ?, ?)",
                (canonical_name, name, '', ''),
            )

    print('Fetching names from db')
    with con as cursor:
        db_canonical_names = {row[0] for row in cursor.execute("SELECT canonical_name FROM projects", ).fetchall()}

    index_canonical_names = {normed_name for normed_name, _ in project_names}
    names_in_db_no_longer_in_index = db_canonical_names - index_canonical_names

    if names_in_db_no_longer_in_index:
        print(
            f'Removing the following { len(names_in_db_no_longer_in_index) } names from the database:\n   '
            + "\n   ".join(names_in_db_no_longer_in_index[:2000])
        )
    with con as cursor:
        for name in names_in_db_no_longer_in_index:
            cursor.execute(
                '''
                DELETE FROM projects
                WHERE canonical_name == ?;
                ''',
                (name, ),
            ),
    print('DB synchronised with index')


async def _devel_to_be_turned_into_test():
    con = sqlite3.connect('../.cache/projects.sqlite')

    create_table(con)

    from ._pypil import SimplePackageIndex

    index = SimplePackageIndex()

    index = SimplePackageIndex(source_url='http://cwe-513-vpl337.cern.ch:8000/simple/')

    if False:
        import asyncio
        asyncio.run(fully_populate_db(con, index))

    name = 'cartop'
    with con as cur:
        # exact = cur.execute("SELECT * FROM projects WHERE canonical_name == ?", (f'{name}',)).fetchone()
        # results = cur.execute("SELECT * FROM projects WHERE canonical_name LIKE ? LIMIT 100", (f'%{name}%', )).fetchall()
        [count] = cur.execute("SELECT COUNT(canonical_name) FROM projects", ).fetchone()

    print(count)


if __name__ == '__main__':
    import asyncio
    asyncio.run(_devel_to_be_turned_into_test())
