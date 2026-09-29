from cosmu.evolution.seeder import seed_breakout_spec
from cosmu.strategy.compiler import compile_spec
from cosmu.strategy.static_check import validate_python, validate_spec


def test_seed_spec_has_no_magic_numbers_and_compiles():
    spec = seed_breakout_spec()
    assert validate_spec(spec) == []
    compiled = compile_spec(
        spec,
        {
            "lookback": 20,
            "entry_ret": 0.03,
            "vol_lookback": 30,
            "vol_floor": 0.02,
            "stop": 0.06,
            "take": 0.12,
            "time_stop": 10,
        },
    )
    assert compiled.code_hash
    assert "COSMU_STRATEGY_V1" in compiled.code


def test_agent_python_static_check_blocks_filesystem_network_escape():
    issues = validate_python("import os\nopen('/tmp/x', 'w')\n")
    assert "blocked_import:os" in issues
    assert "blocked_call:open" in issues

