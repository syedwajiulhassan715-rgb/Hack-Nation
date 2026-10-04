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
def test_unbuilt_stage_fails_loudly(capsys, monkeypatch):
    # Fail closed: a stage whose module does not exist yet must exit non-zero, not print
    # "done". Every real stage is built now, so point one at a missing module.
    monkeypatch.setitem(cli.STAGES, "summaries",
                        ("navigator.not_built_yet", "run", "placeholder", 99))
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
