"""Run the real app against a disposable MySQL database for browser QA.

Requires WALIAPI_TEST_MYSQL_SOCKET and WALIAPI_TEST_PASSWORD_FILE.
The generated administrator password is written to a private temporary file.
No application-configured database or user account is touched.
"""
import os
import secrets
import uuid
from pathlib import Path

from sqlalchemy import URL, create_engine, text

socket = os.environ["WALIAPI_TEST_MYSQL_SOCKET"]
password_path = Path(os.environ["WALIAPI_TEST_PASSWORD_FILE"])
database = "waliapi_ui_test_" + uuid.uuid4().hex
password = secrets.token_urlsafe(24)
descriptor = os.open(password_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(descriptor, "w") as stream:
    stream.write(password)
os.environ.update({
    "DB_UNIX_SOCKET": socket, "DB_NAME": database, "DB_USER": "root", "DB_PASSWORD": "",
    "APP_ENV": "development", "ADMIN_USERNAME": "wiki-ui-admin", "ADMIN_PASSWORD": password,
    "ADMIN_PASSWORD_HASH": "", "ADMIN_SESSION_SECRET": secrets.token_urlsafe(32),
    "ADMIN_SESSION_COOKIE_SECURE": "false", "ADMIN_TOKEN": secrets.token_urlsafe(32),
    "CORS_ALLOWED_ORIGINS": "http://127.0.0.1:18763",
})
admin_engine = create_engine(URL.create("mysql+pymysql", username="root", query={"unix_socket": socket}))
with admin_engine.begin() as connection:
    connection.execute(text(f"CREATE DATABASE {database} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))

try:
    from app.infrastructure.database.connection import engine
    from app.infrastructure.database.migrations import sql_statements

    with engine.begin() as connection:
        for statement in sql_statements(Path("docs/waliapi.sql").read_text()):
            if not statement.upper().startswith(("CREATE DATABASE", "USE ")):
                connection.execute(text(statement))
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=18763, log_level="warning")
finally:
    with admin_engine.begin() as connection:
        connection.execute(text(f"DROP DATABASE {database}"))
    admin_engine.dispose()
    password_path.unlink(missing_ok=True)
