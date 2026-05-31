from cosmu.config.settings import Settings
from cosmu.spine.engine import EngineFacade


def test_seeded_backtest_writes_money_truth(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'cosmu.sqlite3'}", environment="test")
    facade = EngineFacade.create(settings)

    result = facade.run_backtest(seed=42)

    assert result["ok"] is True
    assert result["fills"] > 0
    assert facade.store.row("SELECT id FROM backtests LIMIT 1") is not None
    assert facade.store.row("SELECT id FROM executions LIMIT 1") is not None
    assert facade.store.row("SELECT id FROM events WHERE kind = 'run_completed' LIMIT 1") is not None

