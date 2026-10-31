"""Tests that the pei app registers a working PEAT data-source provider."""

from parseus.webapp.registry import get_data_source_provider


def _ensure_pei_provider_registered():
    """Re-register pei's provider in case another test cleared the registry."""
    from parseus.webapp.pei import data_source

    data_source.register()


def test_pei_registers_peat_provider():
    """pei registers a PeatFileData provider on app ready."""
    _ensure_pei_provider_registered()
    provider = get_data_source_provider("PeatFileData")
    assert provider is not None
    assert provider.key == "peat_file"
    assert provider.enumerable is True


def test_peat_provider_lists_and_resolves(tmp_path):
    """The provider lists pull-run folders and resolves them to paths."""
    from django.test import override_settings

    from parseus.webapp.pei import data_source

    _ensure_pei_provider_registered()

    pull_dir = tmp_path / "peat_pulls"
    (pull_dir / "run_a").mkdir(parents=True)
    (pull_dir / "run_b").mkdir(parents=True)
    (pull_dir / "not_a_dir.txt").write_text("x")

    with override_settings(PEAT_PULL_DIR=pull_dir):
        datasets = data_source.list_pull_datasets()
        ids = [d["id"] for d in datasets]
        assert ids == ["run_a", "run_b"]  # sorted, dirs only
        assert data_source.resolve_pull_path("run_a") == str(pull_dir / "run_a")

    # The registered provider delegates to the same functions.
    provider = get_data_source_provider("PeatFileData")
    with override_settings(PEAT_PULL_DIR=pull_dir):
        assert provider.resolve("run_b") == str(pull_dir / "run_b")
        assert {d["id"] for d in provider.get_datasets()} == {"run_a", "run_b"}


def test_peat_provider_empty_when_dir_missing(tmp_path):
    """Listing returns empty when the pull dir does not exist."""
    from django.test import override_settings

    from parseus.webapp.pei import data_source

    missing = tmp_path / "does_not_exist"
    with override_settings(PEAT_PULL_DIR=missing):
        assert data_source.list_pull_datasets() == []
