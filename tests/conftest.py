"""Test fixtures for HA-USMS.

`helpers.py` pulls in three Home Assistant symbols, none of which the pure
statistics functions actually use. Stubbing them keeps these tests runnable
without installing Home Assistant, so the statistics maths can be covered
cheaply. Integration-level tests still want
`pytest-homeassistant-custom-component`, as noted in TODO.md.
"""

import importlib.util
import pathlib
import sys
import types

import pytest

COMPONENT_DIR = pathlib.Path(__file__).parent.parent / "custom_components" / "ha_usms"
PACKAGE = "ha_usms_under_test"


def _stub_homeassistant() -> None:
    """Register the minimum Home Assistant surface `helpers.py` imports."""
    for name in (
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.recorder",
        "homeassistant.components.recorder.statistics",
        "homeassistant.core",
        "homeassistant.helpers",
        "homeassistant.helpers.recorder",
    ):
        sys.modules.setdefault(name, types.ModuleType(name))

    sys.modules[
        "homeassistant.components.recorder.statistics"
    ].statistics_during_period = None
    sys.modules["homeassistant.core"].HomeAssistant = object
    sys.modules["homeassistant.helpers.recorder"].get_instance = None


def _load_submodule(name: str) -> types.ModuleType:
    """Load a module from the component directory under a synthetic package."""
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE}.{name}", COMPONENT_DIR / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{PACKAGE}.{name}"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def helpers():
    """Return the component's helpers module with Home Assistant stubbed out."""
    _stub_homeassistant()

    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(COMPONENT_DIR)]
    sys.modules[PACKAGE] = package

    # const.py imports nothing from Home Assistant, so use the real one.
    _load_submodule("const")
    return _load_submodule("helpers")
