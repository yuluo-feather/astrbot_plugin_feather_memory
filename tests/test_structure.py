"""结构红线：core/app 不碰 astrbot、版本四件套一致、插件入口可导入。"""
from __future__ import annotations

import ast
import importlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = "data.plugins.astrbot_plugin_feather_memory"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text("utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_core_and_app_do_not_import_astrbot() -> None:
    for folder in ("core", "app"):
        for path in (ROOT / folder).rglob("*.py"):
            names = _imports(path)
            offending = [name for name in names
                         if name == "astrbot" or name.startswith("astrbot.")]
            assert not offending, f"{path} imports {offending}"


def test_core_does_not_import_outer_layers() -> None:
    for path in (ROOT / "core").rglob("*.py"):
        names = _imports(path)
        offending = [name for name in names
                     if name.startswith("adapters") or name.startswith("app")]
        assert not offending, f"{path} imports {offending}"


def test_version_four_pieces_agree() -> None:
    from data.plugins.astrbot_plugin_feather_memory.core.version import VERSION
    assert (ROOT / "VERSION").read_text("utf-8").strip() == VERSION
    metadata = (ROOT / "metadata.yaml").read_text("utf-8")
    assert re.search(rf"^version:\s*{re.escape(VERSION)}$", metadata, re.M)
    assert (ROOT / "changelogs" / f"v{VERSION}.md").exists()
    main_source = (ROOT / "main.py").read_text("utf-8")
    assert "@register(PLUGIN_NAME, \"羽落\", PLUGIN_DESC, VERSION)" in main_source


def test_plugin_class_and_command_live_in_main() -> None:
    """AstrBot 按 main 模块路径绑定 handler；类放子模块会导致未绑定。"""
    module = importlib.import_module(f"{PKG}.main")
    plugin_cls = module.FeatherMemoryPlugin
    assert plugin_cls.__module__ == f"{PKG}.main"
    handler = plugin_cls.feather_memory
    assert handler.__module__ == f"{PKG}.main"
    assert not hasattr(
        importlib.import_module(f"{PKG}.adapters.host"), "FeatherMemoryPlugin")
    main_source = (ROOT / "main.py").read_text("utf-8")
    assert "@filter.command" in main_source


def test_conf_schema_defaults_to_disabled() -> None:
    schema = json.loads((ROOT / "_conf_schema.json").read_text("utf-8"))
    assert schema["memory"]["items"]["enabled"]["default"] is False


def test_entry_module_exposes_plugin() -> None:
    module = importlib.import_module(f"{PKG}.main")
    assert hasattr(module, "FeatherMemoryPlugin")
    assert module.VERSION == "0.1.0"


def test_identity_is_read_from_host_event() -> None:
    host_source = (ROOT / "adapters" / "host.py").read_text("utf-8")
    main_source = (ROOT / "main.py").read_text("utf-8")
    assert "get_platform_id()" in host_source
    assert "get_sender_id()" in host_source
    assert "is_private_chat()" in host_source
    assert "build_user_key(" in main_source


def test_main_has_no_direct_astrbot_import() -> None:
    """宿主符号经 adapters/host.py 转出，main 只定义插件类。"""
    names = _imports(ROOT / "main.py")
    assert not [name for name in names
                if name == "astrbot" or name.startswith("astrbot.")]
