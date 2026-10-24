from host import config


def test_old_settings_folder_is_carried_over(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    old = tmp_path / "OpenSteer"
    (old / "certs").mkdir(parents=True)
    (old / "config.json").write_text('{"token": "keep-me"}')
    (old / "certs" / "ca.crt").write_text("ca")

    assert config.load()["token"] == "keep-me"            # paired phones keep working
    assert (tmp_path / "OpenStear" / "certs" / "ca.crt").read_text() == "ca"
    assert not old.exists()


def test_fresh_install_uses_new_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    cfg = config.load()
    assert cfg["token"]
    assert (tmp_path / "OpenStear" / "config.json").exists()
