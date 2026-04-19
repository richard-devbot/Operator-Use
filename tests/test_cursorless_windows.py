"""Tests for cursorless click path in the Windows computer tool."""

import sys
from unittest.mock import MagicMock

# Stub Windows-only modules so tests run on any platform / in CI.
# The UIA package calls os.sys.getwindowsversion() at import time,
# so we must replace the entire package tree before importing the tool.
_uia_stub = MagicMock()
_vdm_stub = MagicMock()
_win_pkg = MagicMock(uia=_uia_stub, vdm=_vdm_stub)
sys.modules.setdefault("operator_use.computer.windows", _win_pkg)
sys.modules.setdefault("operator_use.computer.windows.uia", _uia_stub)
sys.modules.setdefault("operator_use.computer.windows.vdm", _vdm_stub)
for _mod in [
    "win32gui",
    "win32con",
    "win32api",
    "win32process",
    "pywintypes",
    "ctypes.windll",
]:
    sys.modules.setdefault(_mod, MagicMock())

import asyncio  # noqa: E402

import pytest  # noqa: E402  # ty: ignore[unresolved-import]


@pytest.fixture(autouse=True)
def mock_uia(monkeypatch):
    uia = MagicMock()
    monkeypatch.setattr("operator_use.computer.tools.windows.uia", uia)
    return uia


@pytest.fixture(autouse=True)
def mock_vdm(monkeypatch):
    vdm = MagicMock()
    monkeypatch.setattr("operator_use.computer.tools.windows.vdm", vdm)
    return vdm


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_click_uses_invoke_pattern_when_supported(mock_uia):
    """Left single click should use InvokePattern and NOT call uia.Click."""
    from operator_use.computer.tools.windows import computer

    control = MagicMock()
    mock_uia.ControlFromPoint.return_value = control

    invoke = MagicMock()
    invoke.Invoke.return_value = None  # Windows UIA Invoke is void
    control.GetPattern.return_value = invoke

    result = run(computer.ainvoke(action="click", loc=[100, 200]))

    mock_uia.ControlFromPoint.assert_called_once_with(100, 200)
    control.GetPattern.assert_called_once_with(mock_uia.PatternId.InvokePattern)
    invoke.Invoke.assert_called_once()
    mock_uia.Click.assert_not_called()
    assert result.success


def test_click_falls_back_when_no_invoke_pattern(mock_uia):
    """Falls back to uia.Click when GetPattern returns None."""
    from operator_use.computer.tools.windows import computer

    control = MagicMock()
    mock_uia.ControlFromPoint.return_value = control
    control.GetPattern.return_value = None

    result = run(computer.ainvoke(action="click", loc=[100, 200]))

    mock_uia.Click.assert_called_once_with(100, 200)
    assert result.success


def test_click_falls_back_when_no_control(mock_uia):
    """Falls back to uia.Click when ControlFromPoint returns None."""
    from operator_use.computer.tools.windows import computer

    mock_uia.ControlFromPoint.return_value = None

    result = run(computer.ainvoke(action="click", loc=[100, 200]))

    mock_uia.Click.assert_called_once_with(100, 200)
    assert result.success


def test_right_click_always_uses_coordinates(mock_uia):
    """Right click always uses coordinate path -- context menus need screen position."""
    from operator_use.computer.tools.windows import computer

    result = run(computer.ainvoke(action="click", loc=[100, 200], button="right"))

    mock_uia.ControlFromPoint.assert_not_called()
    mock_uia.RightClick.assert_called_once_with(100, 200)
    assert result.success


def test_double_click_always_uses_coordinates(mock_uia):
    """Double click always uses coordinate path."""
    from operator_use.computer.tools.windows import computer

    result = run(computer.ainvoke(action="click", loc=[100, 200], clicks=2))

    mock_uia.ControlFromPoint.assert_not_called()
    mock_uia.DoubleClick.assert_called_once_with(100, 200)
    assert result.success


def test_invoke_exception_falls_back(mock_uia):
    """If Invoke() raises, fall back silently to uia.Click."""
    from operator_use.computer.tools.windows import computer

    control = MagicMock()
    mock_uia.ControlFromPoint.return_value = control

    invoke = MagicMock()
    invoke.Invoke.side_effect = Exception("UIA error")
    control.GetPattern.return_value = invoke

    result = run(computer.ainvoke(action="click", loc=[100, 200]))

    mock_uia.Click.assert_called_once_with(100, 200)
    assert result.success


def test_get_pattern_exception_falls_back(mock_uia):
    """If GetPattern() raises, fall back silently to uia.Click."""
    from operator_use.computer.tools.windows import computer

    control = MagicMock()
    mock_uia.ControlFromPoint.return_value = control
    control.GetPattern.side_effect = Exception("UIA GetPattern error")

    result = run(computer.ainvoke(action="click", loc=[100, 200]))

    mock_uia.Click.assert_called_once_with(100, 200)
    assert result.success


# --- Cursorless type tests ---


def test_type_uses_value_pattern_when_supported(mock_uia, mock_vdm):
    """Type should use ValuePattern.SetValue and NOT call uia.Click."""
    from operator_use.computer.tools.windows import computer

    control = MagicMock()
    mock_uia.ControlFromPoint.return_value = control

    value_pattern = MagicMock()
    value_pattern.IsReadOnly = False
    control.GetPattern.return_value = value_pattern

    result = run(computer.ainvoke(action="type", loc=[100, 200], text="hello"))

    value_pattern.SetValue.assert_called_once_with("hello")
    mock_uia.Click.assert_not_called()
    assert result.success


def test_type_falls_back_when_caret_position_not_idle(mock_uia, mock_vdm):
    """Type falls back to coordinates when caret_position is not idle."""
    from operator_use.computer.tools.windows import computer

    control = MagicMock()
    mock_uia.ControlFromPoint.return_value = control
    value_pattern = MagicMock()
    value_pattern.IsReadOnly = False
    control.GetPattern.return_value = value_pattern

    result = run(computer.ainvoke(action="type", loc=[100, 200], text="hello", caret_position="end"))

    value_pattern.SetValue.assert_not_called()
    mock_uia.Click.assert_called()
    assert result.success


def test_type_falls_back_when_value_pattern_is_read_only(mock_uia, mock_vdm):
    """Type falls back to coordinates when ValuePattern is ReadOnly."""
    from operator_use.computer.tools.windows import computer

    control = MagicMock()
    mock_uia.ControlFromPoint.return_value = control
    value_pattern = MagicMock()
    value_pattern.IsReadOnly = True
    control.GetPattern.return_value = value_pattern

    result = run(computer.ainvoke(action="type", loc=[100, 200], text="hello"))

    value_pattern.SetValue.assert_not_called()
    mock_uia.Click.assert_called()
    assert result.success


def test_type_press_enter_after_set_value(mock_uia, mock_vdm):
    """press_enter after SetValue fires SendKeys Enter."""
    from operator_use.computer.tools.windows import computer

    control = MagicMock()
    mock_uia.ControlFromPoint.return_value = control
    value_pattern = MagicMock()
    value_pattern.IsReadOnly = False
    control.GetPattern.return_value = value_pattern

    result = run(computer.ainvoke(action="type", loc=[100, 200], text="hello", press_enter=True))

    value_pattern.SetValue.assert_called_once_with("hello")
    mock_uia.SendKeys.assert_called_with("{Enter}", waitTime=0.05)
    mock_uia.Click.assert_not_called()
    assert result.success
