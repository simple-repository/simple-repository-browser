import pathlib
import sqlite3


class YankManager:
    """
    Manager class used to access and edit the Yank information of the acc-py package index.
    The current implementation relies on the SQLite database used to store data for the acc-py index,
    but as this data will be moved to an external service, it will need to be adapted.
    """
    def __init__(self, yank_db_path: pathlib.Path) -> None:
        # Database access is limited to the management of Yank information to avoid excessive coupling.
        # Any other data access or modification operation must be performed using the public index service API.
        self._conn = sqlite3.connect(yank_db_path)

    def is_yanked(self, project_name: str, version: str) -> bool:
        query = "SELECT reason FROM yanked_versions WHERE project_name = :project_name AND version = :version"
        res = self._conn.execute(query, {"project_name": project_name, "version": version}).fetchall()
        return bool(res)

    def yank(self, project_name: str, version: str, reason: str) -> None:
        query = "INSERT INTO yanked_versions (project_name, version, reason) VALUES (:project_name, :version, :reason)"
        try:
            self._conn.execute(query, {"project_name": project_name, "version": version, "reason": reason})
            self._conn.commit()
        except sqlite3.Error:
            # If the INSERT fails, that mean that the package is already yanked.
            # On page refresh the correct information will be displayed to the user.
            pass

    def unyank(self, project_name: str, version: str) -> None:
        query = "DELETE FROM yanked_versions WHERE project_name = :project_name AND version = :version"
        try:
            self._conn.execute(query, {"project_name": project_name, "version": version})
            self._conn.commit()
        except sqlite3.Error:
            pass
