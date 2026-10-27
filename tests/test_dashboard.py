from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def use_submission_snapshot(monkeypatch):
    def no_local_publication(_):
        raise FileNotFoundError
    monkeypatch.setattr("sales_pipeline.model.current_generation", no_local_publication)


def test_dashboard_snapshot_and_filters(monkeypatch):
    use_submission_snapshot(monkeypatch)
    app = AppTest.from_file(str(ROOT / "dashboard.py")).run(timeout=20)
    assert not app.exception
    assert app.selectbox[0].value == 2025
    assert app.selectbox[1].value == "Pittsburgh"
    assert app.metric[0].value == "$100,000"
    assert app.metric[1].value == "$259,700"
    assert any("submission snapshot" in caption.value for caption in app.caption)
    app.selectbox[0].set_value(2026).run()
    assert not app.exception
    assert any("partial-year" in warning.value for warning in app.warning)
    app.selectbox[1].set_value("Wilkinsburg").run()
    app.selectbox[2].set_value(100).run()
    assert not app.exception
    assert any("below the 100-sale" in warning.value for warning in app.warning)


def test_market_table_is_downloadable(monkeypatch):
    use_submission_snapshot(monkeypatch)
    app = AppTest.from_file(str(ROOT / "dashboard.py")).run(timeout=20)
    assert not app.exception
    assert len(app.get("download_button")) == 2
    assert len(app.dataframe) == 3
