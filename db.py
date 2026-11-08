"""Database connection layer for Freshlane.

Default: local SQLite.  Optional: Amazon RDS for MySQL / Aurora MySQL.
Configuration is read from environment variables so credentials never belong in
source control. See .env.example and README.md.
"""
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = os.environ.get("DB_BACKEND", "sqlite").strip().lower()
SQLITE_PATH = Path(os.environ.get("GROCERY_DB", str(ROOT / "data" / "grocery.db")))

# The application resolves these names at exception-handling time. They are
# expanded with PyMySQL's native errors only when the RDS backend is selected.
IntegrityError = sqlite3.IntegrityError
OperationalError = sqlite3.OperationalError


class SQLiteConnection(sqlite3.Connection):
    """SQLite connection that commits/rolls back and closes in a with block."""

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

    def begin_write(self):
        self.execute("BEGIN IMMEDIATE")


class MySQLConnection:
    """Small adapter exposing the SQLite-shaped API used by the application."""

    def __init__(self, raw):
        self.raw = raw

    @staticmethod
    def _sql(sql):
        # Project queries only use qmark placeholders for parameters; converting
        # them keeps all values parameterized for both supported backends.
        return sql.replace("?", "%s")

    def execute(self, sql, args=()):
        cursor = self.raw.cursor()
        cursor.execute(self._sql(sql), args)
        return cursor

    def executescript(self, script):
        cursor = self.raw.cursor()
        for statement in script.split(";"):
            if statement.strip():
                cursor.execute(statement)
        cursor.close()

    def begin_write(self):
        self.raw.begin()

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc, _traceback):
        try:
            self.rollback() if exc_type else self.commit()
        finally:
            self.close()


def _mysql_driver():
    global IntegrityError, OperationalError
    try:
        import pymysql
    except ImportError as error:
        raise RuntimeError(
            "RDS MySQL support needs PyMySQL. Run: pip install -r requirements.txt"
        ) from error
    IntegrityError = (sqlite3.IntegrityError, pymysql.err.IntegrityError)
    OperationalError = (sqlite3.OperationalError, pymysql.err.OperationalError)
    return pymysql


def _required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be set when DB_BACKEND=mysql.")
    return value


def connect():
    if BACKEND == "sqlite":
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(SQLITE_PATH, timeout=15, factory=SQLiteConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db
    if BACKEND != "mysql":
        raise RuntimeError("DB_BACKEND must be either 'sqlite' or 'mysql'.")

    pymysql = _mysql_driver()
    port = int(os.environ.get("RDS_PORT", "3306"))
    ssl_ca = os.environ.get("RDS_SSL_CA", "").strip()
    connection_options = {
        "host": _required("RDS_HOST"),
        "port": port,
        "user": _required("RDS_USER"),
        "password": _required("RDS_PASSWORD"),
        "database": _required("RDS_DATABASE"),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": False,
        "connect_timeout": 10,
        "read_timeout": 30,
        "write_timeout": 30,
    }
    if ssl_ca:
        connection_options["ssl"] = {"ca": ssl_ca, "check_hostname": True}
    return MySQLConnection(pymysql.connect(**connection_options))
