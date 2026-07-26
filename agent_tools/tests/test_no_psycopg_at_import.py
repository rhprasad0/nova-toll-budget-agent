import sys


def test_i66_route_module_imports_without_psycopg():
    # psycopg is a real dependency now (pyproject.toml), but _env_connect()
    # imports it lazily inside the function -- importing the module itself
    # must never pull it in, matching the same discipline
    # lambdas/loader/tests/test_loader_handler.py enforces for handler.py.
    import i66_route  # noqa: F401

    assert "psycopg" not in sys.modules


def test_i95_route_module_imports_without_psycopg():
    import i95_route  # noqa: F401

    assert "psycopg" not in sys.modules


def test_i495_route_module_imports_without_psycopg():
    import i495_route  # noqa: F401

    assert "psycopg" not in sys.modules
