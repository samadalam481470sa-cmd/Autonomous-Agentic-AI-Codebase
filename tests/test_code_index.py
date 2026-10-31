from services.api import code_index,engine

def test_incremental_index(tmp_path,monkeypatch):
 monkeypatch.setattr(engine,"ROOT",tmp_path)
 root=tmp_path/"demo";root.mkdir()
 (root/"main.py").write_text("def calculate_invoice():\n    return 42\n")
 monkeypatch.setenv("AGENT_ADMIN_TOKEN","secret")
 auth="Bearer secret"
 first=code_index.refresh(code_index.Request(project="demo"),auth)
 assert first["updated"]==1
 assert code_index.search(code_index.Query(project="demo",query="calculate_invoice"),auth)["results"]
 second=code_index.refresh(code_index.Request(project="demo"),auth)
 assert second["updated"]==0
 (root/"main.py").write_text("def calculate_receipt():\n    return 42\n")
 assert code_index.refresh(code_index.Request(project="demo"),auth)["updated"]==1
 assert not code_index.search(code_index.Query(project="demo",query="calculate_invoice"),auth)["results"]
