"""Version bundles carry exactly the staged runtime, without store metadata."""

import zipfile

from scripts import build_update_bundle


def test_bundle_contains_versioned_payload(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "bundle.zip"

    def stage_payload(**arguments):
        stage = arguments["output"]
        stage.mkdir()
        (stage / "VERSION").write_text("0.9.1\n", encoding="utf-8")
        (stage / "store-payload.json").write_text("{}", encoding="utf-8")
        return stage

    monkeypatch.setattr(build_update_bundle, "stage_payload", stage_payload)
    monkeypatch.setattr(build_update_bundle, "native_runtime", lambda *_: None)
    build_update_bundle.build(source, tmp_path, tmp_path, tmp_path / "cache", output)
    with zipfile.ZipFile(output) as bundle:
        assert set(bundle.namelist()) == {"VERSION", "update-bundle.json"}
        assert bundle.read("VERSION").decode("utf-8").splitlines() == ["0.9.1"]
