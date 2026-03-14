import os
import tempfile
import yaml
from llm_chat.config import Config, LLMConfig


def test_default_config():
    """测试默认配置"""
    config = Config()
    assert config.llm.base_url == "https://api.openai.com/v1"
    assert config.llm.model == "gpt-3.5-turbo"
    assert config.llm.api_key is None
    assert config.llm.timeout == 30
    assert config.llm.max_retries == 3


def test_yaml_config():
    """测试从 YAML 文件加载配置"""
    # 创建临时配置文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        config_data = {
            "llm": {
                "base_url": "https://api.example.com/v1",
                "model": "gpt-4",
                "api_key": "test-api-key",
                "timeout": 60,
                "max_retries": 5
            }
        }
        yaml.dump(config_data, f)
        config_path = f.name

    try:
        config = Config.from_yaml(config_path)
        assert config.llm.base_url == "https://api.example.com/v1"
        assert config.llm.model == "gpt-4"
        assert config.llm.api_key == "test-api-key"
        assert config.llm.timeout == 60
        assert config.llm.max_retries == 5
    finally:
        os.unlink(config_path)


def test_env_vars():
    """测试环境变量覆盖配置"""
    # 设置环境变量
    os.environ["LLM_BASE_URL"] = "https://api.env.com/v1"
    os.environ["LLM_MODEL"] = "env-model"
    os.environ["LLM_API_KEY"] = "env-api-key"
    os.environ["LLM_TIMEOUT"] = "45"
    os.environ["LLM_MAX_RETRIES"] = "2"

    try:
        # 创建新的配置实例
        config = Config()
        assert config.llm.base_url == "https://api.env.com/v1"
        assert config.llm.model == "env-model"
        assert config.llm.api_key == "env-api-key"
        assert config.llm.timeout == 45
        assert config.llm.max_retries == 2
    finally:
        # 清理环境变量
        del os.environ["LLM_BASE_URL"]
        del os.environ["LLM_MODEL"]
        del os.environ["LLM_API_KEY"]
        del os.environ["LLM_TIMEOUT"]
        del os.environ["LLM_MAX_RETRIES"]
