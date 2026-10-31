"""Model profile loading and agent construction (keys from env only)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agb.config import ModelProfile, build_agent, load_model_profiles

YAML = """
profiles:
  local-test:
    base_url: http://localhost:11434/v1
    model: test-vision:1b
  hosted-test:
    base_url: https://api.example.com/v1
    model: vendor/big-model
    api_key_env: TEST_PROFILE_KEY
    price_in: 2.5
    price_out: 10.0
"""


@pytest.fixture
def profiles_file(tmp_path):
    p = tmp_path / "models.yaml"
    p.write_text(YAML, encoding="utf-8")
    return p


class TestLoadProfiles:
    def test_loads_and_validates(self, profiles_file):
        profiles = load_model_profiles(profiles_file)
        assert set(profiles) == {"local-test", "hosted-test"}
        assert profiles["local-test"].api_key_env is None
        assert profiles["hosted-test"].price_in == 2.5
        assert profiles["hosted-test"].vision is True

    def test_rejects_bad_profile(self, tmp_path):
        p = tmp_path / "models.yaml"
        p.write_text("profiles:\n  bad:\n    model: x\n", encoding="utf-8")
        with pytest.raises(ValidationError):  # base_url missing
            load_model_profiles(p)


class TestBuildAgent:
    def test_unknown_profile_raises(self, profiles_file):
        with pytest.raises(KeyError):
            build_agent("nope", profiles_file)

    def test_missing_env_key_is_hard_error(self, profiles_file, monkeypatch):
        monkeypatch.delenv("TEST_PROFILE_KEY", raising=False)
        with pytest.raises(RuntimeError, match="TEST_PROFILE_KEY"):
            build_agent("hosted-test", profiles_file)

    def test_builds_local_agent_without_key(self, profiles_file):
        agent = build_agent("local-test", profiles_file)
        assert agent.name == "local-test"
        assert agent.model == "test-vision:1b"

    def test_builds_hosted_agent_with_key(self, profiles_file, monkeypatch):
        monkeypatch.setenv("TEST_PROFILE_KEY", "sk-test")
        agent = build_agent("hosted-test", profiles_file)
        assert agent.model == "vendor/big-model"
        assert agent.price_in == 2.5

    def test_profile_model_rejects_empty_url(self):
        with pytest.raises(ValidationError):
            ModelProfile.model_validate({"model": "x"})
