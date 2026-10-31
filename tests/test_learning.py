import pytest
from fastapi import HTTPException
from services.api import engine,learning

def test_feedback_requires_consent_and_stores_locally(tmp_path,monkeypatch):
    monkeypatch.setattr(engine,"ROOT",tmp_path)
    monkeypatch.setenv("AGENT_ADMIN_TOKEN","test-token")
    unauthorized=learning.Feedback(project="demo",prompt="test?",accepted_response="good",consent=False)
    with pytest.raises(HTTPException) as exc:
        learning.feedback(unauthorized,"Bearer test-token")
    assert exc.value.status_code==428
    record=learning.Feedback(project="demo",prompt="test?",accepted_response="good",consent=True)
    result=learning.feedback(record,"Bearer test-token")
    assert result["stored_locally"]
    assert not result["trained"]
    assert learning.status("demo","Bearer test-token")["feedback_examples"]==1

def test_evaluation_rejects_regression(tmp_path,monkeypatch):
    monkeypatch.setattr(engine,"ROOT",tmp_path)
    monkeypatch.setenv("AGENT_ADMIN_TOKEN","test-token")
    bad=learning.Evaluation(project="demo",candidate="bad-candidate",passed=5,total=10,baseline_passed=7)
    result=learning.evaluation(bad,"Bearer test-token")
    assert not result["approved"]
    assert not result["model_switched"]
    good=learning.Evaluation(project="demo",candidate="good-candidate",passed=9,total=10,baseline_passed=7,min_improvement=0.1)
    assert learning.evaluation(good,"Bearer test-token")["approved"]
    assert not learning.status("demo","Bearer test-token")["gpu_training_enabled"]
