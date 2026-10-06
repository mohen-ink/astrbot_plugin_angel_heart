import json
from pathlib import Path
from astrbot_plugin_angel_heart.core.config_manager import ConfigManager


def test_schema_has_debug_log_context_to_file():
    schema_path = Path(__file__).parent.parent / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert "debug" in schema
    assert "log_context_to_file" in schema["debug"]["items"]
    assert schema["debug"]["items"]["log_context_to_file"]["type"] == "bool"
    assert schema["debug"]["items"]["log_context_to_file"]["default"] is False


def test_config_manager_reads_debug_log_context_to_file():
    # 默认值
    cm = ConfigManager({})
    assert cm.log_context_to_file is False

    # 显式开启
    cm_enabled = ConfigManager({"debug": {"log_context_to_file": True}})
    assert cm_enabled.log_context_to_file is True

    # 显式关闭
    cm_disabled = ConfigManager({"debug": {"log_context_to_file": False}})
    assert cm_disabled.log_context_to_file is False
