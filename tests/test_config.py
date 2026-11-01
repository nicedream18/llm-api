from urllib.parse import parse_qs, urlsplit

from app.config import DatabaseConfig


def test_mysql_socket_configuration_encodes_socket_and_credentials():
    config = DatabaseConfig(host="127.0.0.1", port=3306, name="test",
                            user="test-user", password="only-test", unix_socket="/tmp/mysql test/mysql.sock")
    parsed = urlsplit(config.url)
    assert parse_qs(parsed.query)["unix_socket"] == ["/tmp/mysql test/mysql.sock"]
    assert parsed.hostname == "127.0.0.1"
