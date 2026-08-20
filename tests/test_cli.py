import pytest

from lighter_trader.cli import main


def test_cli_runs_one_paper_cycle(capsys):
    assert main(["--iterations", "1"]) == 0
    assert "paper_orders=1" in capsys.readouterr().out


def test_cli_rejects_live_mode():
    with pytest.raises(SystemExit) as exc:
        main(["--mode", "live", "--iterations", "1"])
    assert exc.value.code == 2
