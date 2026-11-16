


"""Step 1 tests: no database needed, so they run anywhere (including GitHub)."""
import pytest

from monthly_pack import db


def test_default_url_points_at_local_sqlexpress(monkeypatch):
    monkeypatch.delenv("DB_URL", raising=False)
    url = db.connection_url()
    assert url.startswith("mssql+pyodbc:///?odbc_connect=")
    assert "SQLEXPRESS" in url and "Vendor_sales" in url


def test_db_url_in_env_wins(monkeypatch):
    monkeypatch.setenv("DB_URL", "sqlite://")
    assert db.connection_url() == "sqlite://"


def test_unknown_view_is_refused_before_any_sql_runs():
    with pytest.raises(ValueError, match="not one of the pack's views"):
        db.read_view("vendor_sales_summary; DROP TABLE x")