from cosmu.config.settings import Settings
from cosmu.spine.engine import EngineFacade


def test_create_seeds_venue_catalog(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'cosmu.sqlite3'}", environment="test")
    facade = EngineFacade.create(settings)
    assert facade.store.row("SELECT id FROM venues LIMIT 1") is not None
    assert facade.store.row("SELECT id FROM instruments LIMIT 1") is not None


def test_seed_catalog_is_idempotent(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'cosmu.sqlite3'}", environment="test")
    facade = EngineFacade.create(settings)
    count_before = facade.store.rows("SELECT COUNT(*) AS n FROM venues")[0]["n"]
    facade.seed_catalog()  # second call — ON CONFLICT DO NOTHING
    count_after = facade.store.rows("SELECT COUNT(*) AS n FROM venues")[0]["n"]
    assert count_before == count_after
