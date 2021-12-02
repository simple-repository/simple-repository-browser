import sqlite3
con = sqlite3.connect('../.cache/projects.sqlite')

with con as cursor:
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS projects
        (canonical_name text unique, preferred_name text, summary text, description_html text)
        '''
    )


from pypil.simple.index import SimplePackageIndex
index = SimplePackageIndex()


from pypil.in_memory.project import InMemoryProject, InMemoryProjectRelease, InMemoryProjectFile
from pypil.in_memory.index import InMemoryPackageIndex
from pypil.core.package_name import PackageName


pkgs = [
    InMemoryProject(
        name=PackageName('pkg-a'),
        releases=InMemoryProjectRelease.build_from_files([
            InMemoryProjectFile('', version='1.2.3b0'),
            InMemoryProjectFile('', version='1.2.1'),
            # InMemoryPackageRelease(version='1.2.1', dist_metadata='wheel...'),
            InMemoryProjectFile('', version='0.9'),
        ]),
    )
]
# index = InMemoryPackageIndex(pkgs)


from pypil.core.package_name import PackageName

if False:
    cursor = con.cursor()
    for i, project in enumerate(index.project_names()):
        con.execute(
            "insert OR IGNORE into projects(canonical_name, preferred_name, summary, description_html) values (?, ?, ?, ?)",
            (PackageName(project).normalized, project, '', ''),
        )
        # print(project)
        # if i > 1000:
        #     break
    con.commit()



name = 'cartop'
with con as cur:
    # exact = cur.execute("SELECT * FROM projects WHERE canonical_name == ?", (f'{name}',)).fetchone()
    # results = cur.execute("SELECT * FROM projects WHERE canonical_name LIKE ? LIMIT 100", (f'%{name}%', )).fetchall()
    results = cur.execute("SELECT * FROM projects", ).fetchall()

# from Levenshtein import ratio
#
# results = sorted(results, key=lambda result: ratio(name, result[0]), reverse=True)
# for result in results:
#     print(result[0])
#
# print(exact)

print(len(results))
