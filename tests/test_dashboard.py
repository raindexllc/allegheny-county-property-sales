from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def submission_only(monkeypatch):
    def no_local(_):
        raise FileNotFoundError

    monkeypatch.setattr("sales_pipeline.storage.current_generation", no_local)


def test_default_finding_and_opposite_example(monkeypatch):
    submission_only(monkeypatch)
    app = AppTest.from_file(str(ROOT / "dashboard.py")).run(timeout=20)
    assert not app.exception
    assert app.selectbox[0].value == 2025
    assert app.selectbox[1].value == "Pittsburgh"
    text = " ".join(m.value for m in app.markdown)
    assert "$100,000" in text and "$259,700" in text and "$1" in text
    assert "\\$100,000" in text and "\\$259,700" in text
    app.button[1].click().run()
    assert not app.exception
    assert app.selectbox[0].value == 2020
    assert app.selectbox[1].value == "Clairton"
    text = " ".join(m.value for m in app.markdown)
    assert "$164,000" in text and "$56,500" in text
    assert any("173" in caption.value and "$185,000" in caption.value for caption in app.caption)


def test_partial_year_and_empty_comparison(monkeypatch):
    submission_only(monkeypatch)
    app = AppTest.from_file(str(ROOT / "dashboard.py")).run(timeout=20)
    app.selectbox[0].set_value(2026).run()
    assert not app.exception
    assert any("partial" in warning.value for warning in app.warning)
    app.selectbox[0].set_value(2025).run()
    app.selectbox[3].set_value("Lower standard-valid medians").run()
    assert not app.exception
    assert any("No municipalities meet" in item.value for item in app.info)


def test_bad_pointer_and_bundle_show_controlled_error(monkeypatch):
    monkeypatch.setattr(
        "sales_pipeline.storage.current_generation",
        lambda _: (_ for _ in ()).throw(ValueError("Invalid publication pointer")),
    )
    app = AppTest.from_file(str(ROOT / "dashboard.py")).run(timeout=20)
    assert not app.exception
    assert app.error and "Invalid publication" in app.error[0].value


def test_missing_local_data_uses_labeled_snapshot_and_downloads(monkeypatch):
    submission_only(monkeypatch)
    app = AppTest.from_file(str(ROOT / "dashboard.py")).run(timeout=20)
    assert not app.exception
    assert any("submission snapshot" in item.value for item in app.caption)
    assert len(app.get("download_button")) == 2


def test_corrupt_bundle_shows_error(monkeypatch):
    submission_only(monkeypatch)

    def corrupt(_):
        raise ValueError("Publication checksum mismatch: source_reconciliation.csv")

    monkeypatch.setattr("sales_pipeline.storage.verify_bundle", corrupt)
    app = AppTest.from_file(str(ROOT / "dashboard.py")).run(timeout=20)
    assert not app.exception
    assert app.error and "checksum mismatch" in app.error[0].value
