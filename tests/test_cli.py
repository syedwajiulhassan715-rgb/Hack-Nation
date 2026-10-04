import pytest

from navigator import cli, settings


@pytest.mark.smoke
def test_settings_paths_exist():
    for key in ("manifest", "addresses", "schema", "change_tests"):
        assert settings.path(key).is_file(), key


@pytest.mark.smoke
def test_help_runs(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for stage in ("ingest", "extract", "verify", "geocode", "lookups", "changes", "eval", "api"):
        assert stage in out


@pytest.mark.smoke
def test_unbuilt_stage_fails_loudly(capsys):
    # Fail closed: a stage that does not exist yet must exit non-zero, not print "done".
    # Update the stage name here when its phase lands.
    assert cli.main(["summaries"]) == 2
    assert "not implemented" in capsys.readouterr().err


@pytest.mark.smoke
def test_missing_dependency_is_not_reported_as_unbuilt(monkeypatch):
    # A built stage whose third-party import fails must raise, not look "unbuilt".
    def fake_import(name):
        raise ModuleNotFoundError("No module named 'anthropic'", name="anthropic")

    monkeypatch.setattr(cli.importlib, "import_module", fake_import)
    with pytest.raises(ModuleNotFoundError):
        cli._run_stage("extract")
