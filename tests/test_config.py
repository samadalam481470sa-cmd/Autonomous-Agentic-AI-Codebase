import os

from services.api.config import load_env_file


def _clear(monkeypatch, *keys):
    for key in keys:
        monkeypatch.delenv(key, raising=False)


def test_load_env_file_applies_documented_values(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "# local configuration",
                'export MODEL_NAME="mock-model"',
                "MODEL_BASE_URL=http://127.0.0.1:9099/v1",
                "INLINE=value # a comment",
                "LITERAL='keep # this'",
                'ESCAPED="line\\nnext"',
                "EMPTY=",
                "NOT A KEY=ignored",
                "NO_EQUALS",
            ]
        ),
        encoding="utf-8",
    )
    keys = ("MODEL_NAME", "MODEL_BASE_URL", "INLINE", "LITERAL", "ESCAPED", "EMPTY")
    _clear(monkeypatch, *keys)

    assert load_env_file(env) == 6
    assert os.environ["MODEL_NAME"] == "mock-model"
    assert os.environ["MODEL_BASE_URL"] == "http://127.0.0.1:9099/v1"
    assert os.environ["INLINE"] == "value"
    assert os.environ["LITERAL"] == "keep # this"
    assert os.environ["ESCAPED"] == "line\nnext"
    assert os.environ["EMPTY"] == ""


def test_explicit_environment_wins_and_missing_file_is_harmless(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("MODEL_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("MODEL_API_KEY", "from-process")

    assert load_env_file(env) == 0
    assert os.environ["MODEL_API_KEY"] == "from-process"
    assert load_env_file(tmp_path / "missing.env") == 0
