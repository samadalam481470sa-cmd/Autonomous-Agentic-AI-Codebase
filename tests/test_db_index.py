from services.api import engine

def test_sqlite_history_index_and_wal(tmp_path,monkeypatch):
    monkeypatch.setattr(engine,"DB",tmp_path/"history.sqlite")
    for i in range(40):engine.save("p","user",str(i))
    assert len(engine.history("p"))==30
    assert engine.history("p")[-1]["content"]=="39"
    with engine.db() as con:
        indexes={row[1] for row in con.execute("PRAGMA index_list(messages)")}
        assert "idx_messages_project_history" in indexes
        assert con.execute("PRAGMA journal_mode").fetchone()[0]=="wal"
