import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

spec=importlib.util.spec_from_file_location("local_stack",Path(__file__).resolve().parents[1]/"scripts"/"local_stack.py")
stack=importlib.util.module_from_spec(spec)
spec.loader.exec_module(stack)

def test_rejects_missing_model(tmp_path):
    with pytest.raises(RuntimeError,match="existing local"):
        stack.config(SimpleNamespace(model=str(tmp_path/"missing.gguf"),context=4096,gpu_layers=99))

def test_rejects_non_gguf(tmp_path):
    p=tmp_path/"bad.bin";p.write_bytes(b"x")
    with pytest.raises(RuntimeError,match="gguf"):
        stack.config(SimpleNamespace(model=str(p),context=4096,gpu_layers=99))

def test_accepts_gguf(tmp_path):
    p=tmp_path/"code.gguf";p.write_bytes(b"GGUF")
    assert stack.config(SimpleNamespace(model=str(p),context=4096,gpu_layers=0))==p

def test_rejects_bad_context(tmp_path):
    p=tmp_path/"code.gguf";p.write_bytes(b"GGUF")
    with pytest.raises(RuntimeError,match="Context"):
        stack.config(SimpleNamespace(model=str(p),context=1,gpu_layers=0))

def test_process_group_options_match_the_host_platform():
    import os
    options=stack.process_group_options()
    if os.name=="nt":
        assert "creationflags" in options
    else:
        assert options=={"start_new_session":True}

def test_terminate_tree_skips_an_already_finished_process():
    class Finished:
        def poll(self):return 0
        def terminate(self):raise AssertionError("must not terminate a finished process")
    stack.terminate_tree(Finished())
