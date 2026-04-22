from scanner.core.config import PolilyConfig, load_config


def test_wallet_config_default():
    cfg = PolilyConfig()
    assert cfg.wallet.starting_balance == 100.0


def test_wallet_config_override(tmp_path):
    yml = tmp_path / "cfg.yaml"
    yml.write_text("wallet:\n  starting_balance: 250.0\n")
    cfg = load_config(yml)
    assert cfg.wallet.starting_balance == 250.0
