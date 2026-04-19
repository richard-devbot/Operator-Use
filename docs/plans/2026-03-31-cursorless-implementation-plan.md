# Cursorless UI Automation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Route `click` and `type` actions through OS accessibility APIs instead of hardware input events, so the agent never moves the user's cursor or steals focus.

**Architecture:** At action time, resolve the AX/UIA element under the given coordinates using `ax.ElementAtPosition()` (macOS) or `uia.ControlFromPoint()` (Windows). Try the cursorless pattern first (`InvokePattern.Invoke()` for click, `ValuePattern.SetValue()` for type). Fall back silently to the existing coordinate path if the element isn't found or the pattern isn't supported. Only two files change: `computer/tools/macos.py` and `computer/tools/windows.py`.

**Tech Stack:** Python, macOS Accessibility API (`AXUIElementCopyElementAtPosition`), Windows UI Automation (`IUIAutomation::ElementFromPoint`), pytest, unittest.mock

---

## Task 1: macOS — cursorless click

**Files:**
- Modify: `operator_use/computer/tools/macos.py` — `click` action block (lines 193–213)
- Create: `tests/test_cursorless_macos.py`

**Step 1: Write the failing test**

```python
# tests/test_cursorless_macos.py
import pytest
from unittest.mock import MagicMock, patch
import asyncio

# Patch the ax module before any import of the tool
@pytest.fixture(autouse=True)
def mock_ax(monkeypatch):
    ax = MagicMock()
    monkeypatch.setattr("operator_use.computer.tools.macos.ax", ax)
    return ax

@pytest.fixture(autouse=True)
def mock_ax_patterns(monkeypatch):
    patterns = MagicMock()
    monkeypatch.setattr("operator_use.computer.tools.macos.ax_patterns", patterns)
    return patterns

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)

def test_click_uses_invoke_pattern_when_supported(mock_ax, mock_ax_patterns):
    """Left single click should use InvokePattern and NOT call ax.Click."""
    from operator_use.computer.tools.macos import computer

    element = MagicMock()
    mock_ax.ElementAtPosition.return_value = element
    mock_ax.GetRootControl.return_value = MagicMock()

    invoke = MagicMock()
    invoke.Invoke.return_value = True
    mock_ax_patterns.InvokePattern.IsSupported.return_value = True
    mock_ax_patterns.InvokePattern.return_value = invoke

    result = run(computer(action="click", loc=[100, 200]))

    mock_ax_patterns.InvokePattern.IsSupported.assert_called_once_with(element)
    invoke.Invoke.assert_called_once()
    mock_ax.Click.assert_not_called()
    assert result.is_success


def test_click_falls_back_when_invoke_not_supported(mock_ax, mock_ax_patterns):
    """Falls back to ax.Click when InvokePattern is not supported."""
    from operator_use.computer.tools.macos import computer

    element = MagicMock()
    mock_ax.ElementAtPosition.return_value = element
    mock_ax.GetRootControl.return_value = MagicMock()
    mock_ax_patterns.InvokePattern.IsSupported.return_value = False

    result = run(computer(action="click", loc=[100, 200]))

    mock_ax.Click.assert_called_once_with(100, 200)
    assert result.is_success


def test_click_falls_back_when_no_element(mock_ax, mock_ax_patterns):
    """Falls back to ax.Click when no element found at position."""
    from operator_use.computer.tools.macos import computer

    mock_ax.ElementAtPosition.return_value = None
    mock_ax.GetRootControl.return_value = MagicMock()

    result = run(computer(action="click", loc=[100, 200]))

    mock_ax.Click.assert_called_once_with(100, 200)
    assert result.is_success


def test_right_click_always_uses_coordinates(mock_ax, mock_ax_patterns):
    """Right click always uses coordinate path — context menus need screen position."""
    from operator_use.computer.tools.macos import computer

    result = run(computer(action="click", loc=[100, 200], button="right"))

    mock_ax_patterns.InvokePattern.IsSupported.assert_not_called()
    mock_ax.RightClick.assert_called_once_with(100, 200)
    assert result.is_success


def test_double_click_always_uses_coordinates(mock_ax, mock_ax_patterns):
    """Double click always uses coordinate path — file-open semantics need events."""
    from operator_use.computer.tools.macos import computer

    result = run(computer(action="click", loc=[100, 200], clicks=2))

    mock_ax_patterns.InvokePattern.IsSupported.assert_not_called()
    mock_ax.DoubleClick.assert_called_once_with(100, 200)
    assert result.is_success


def test_invoke_exception_falls_back(mock_ax, mock_ax_patterns):
    """If Invoke() raises, fall back silently to ax.Click."""
    from operator_use.computer.tools.macos import computer

    element = MagicMock()
    mock_ax.ElementAtPosition.return_value = element
    mock_ax.GetRootControl.return_value = MagicMock()
    mock_ax_patterns.InvokePattern.IsSupported.return_value = True
    mock_ax_patterns.InvokePattern.return_value.Invoke.side_effect = Exception("AX error")

    result = run(computer(action="click", loc=[100, 200]))

    mock_ax.Click.assert_called_once_with(100, 200)
    assert result.is_success
```

**Step 2: Run test to verify it fails**

```bash
cd /Users/richardsongunde/projects/Operator-Use
python -m pytest tests/test_cursorless_macos.py -v 2>&1 | head -30
```

Expected: `ImportError` or `AttributeError` — `ax_patterns` not imported in tool module yet.

**Step 3: Implement**

At the top of `operator_use/computer/tools/macos.py`, add after the existing `ax` import:

```python
from operator_use.computer.macos.ax import patterns as ax_patterns
```

Replace the `case "click":` block (lines 193–213) with:

```python
        case "click":
            if not loc:
                return ToolResult.error_result("loc is required for click.")
            x, y = loc[0], loc[1]
            if clicks == 0:
                ax.SetCursorPos(x, y)
                return ToolResult.success_result(f"Moved cursor to ({x},{y}).")
            # Cursorless path: only for left single clicks
            if button == "left" and clicks == 1:
                try:
                    element = ax.ElementAtPosition(ax.GetRootControl(), x, y)
                    if element and ax_patterns.InvokePattern.IsSupported(element):
                        if ax_patterns.InvokePattern(element).Invoke():
                            return ToolResult.success_result(f"Single left clicked at ({x},{y}).")
                except Exception:
                    pass
            # Coordinate fallback
            ax.MoveTo(x, y)
            await asyncio.sleep(0.05)
            match button:
                case "right":
                    ax.RightClick(x, y)
                case "middle":
                    ax.MiddleClick(x, y)
                case "left":
                    if clicks >= 2:
                        ax.DoubleClick(x, y)
                    else:
                        ax.Click(x, y)
            labels = {1: "Single", 2: "Double", 3: "Triple"}
            return ToolResult.success_result(f"{labels.get(clicks, str(clicks))} {button} clicked at ({x},{y}).")
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_cursorless_macos.py -v
```

Expected: All 6 tests pass.

**Step 5: Commit**

```bash
git add operator_use/computer/tools/macos.py tests/test_cursorless_macos.py
git commit -m "feat(macos): cursorless click via InvokePattern with coordinate fallback"
```

---

## Task 2: macOS — cursorless type

**Files:**
- Modify: `operator_use/computer/tools/macos.py` — `type` action block (lines 215–237)
- Modify: `tests/test_cursorless_macos.py` — add type tests

**Step 1: Write the failing tests** (append to `tests/test_cursorless_macos.py`)

```python
def test_type_uses_value_pattern_when_supported(mock_ax, mock_ax_patterns):
    """Type should use ValuePattern.SetValue and NOT call ax.Click or ax.TypeText."""
    from operator_use.computer.tools.macos import computer

    element = MagicMock()
    mock_ax.ElementAtPosition.return_value = element
    mock_ax.GetRootControl.return_value = MagicMock()

    value_pattern = MagicMock()
    value_pattern.IsReadOnly = False
    value_pattern.SetValue.return_value = True
    mock_ax_patterns.ValuePattern.IsSupported.return_value = True
    mock_ax_patterns.ValuePattern.return_value = value_pattern

    result = run(computer(action="type", loc=[100, 200], text="hello"))

    value_pattern.SetValue.assert_called_once_with("hello")
    mock_ax.Click.assert_not_called()
    mock_ax.TypeText.assert_not_called()
    assert result.is_success


def test_type_clears_before_set_when_clear_true(mock_ax, mock_ax_patterns):
    """With clear=True, SetValue is called with just the new text (replaces all)."""
    from operator_use.computer.tools.macos import computer

    element = MagicMock()
    mock_ax.ElementAtPosition.return_value = element
    mock_ax.GetRootControl.return_value = MagicMock()

    value_pattern = MagicMock()
    value_pattern.IsReadOnly = False
    value_pattern.Value = "old content"
    mock_ax_patterns.ValuePattern.IsSupported.return_value = True
    mock_ax_patterns.ValuePattern.return_value = value_pattern

    result = run(computer(action="type", loc=[100, 200], text="new", clear=True))

    value_pattern.SetValue.assert_called_once_with("new")
    assert result.is_success


def test_type_falls_back_when_readonly(mock_ax, mock_ax_patterns):
    """Falls back to click+TypeText when ValuePattern is ReadOnly."""
    from operator_use.computer.tools.macos import computer

    element = MagicMock()
    mock_ax.ElementAtPosition.return_value = element
    mock_ax.GetRootControl.return_value = MagicMock()

    value_pattern = MagicMock()
    value_pattern.IsReadOnly = True
    mock_ax_patterns.ValuePattern.IsSupported.return_value = True
    mock_ax_patterns.ValuePattern.return_value = value_pattern

    result = run(computer(action="type", loc=[100, 200], text="hello"))

    mock_ax.Click.assert_called()
    mock_ax.TypeText.assert_called_once_with("hello")
    assert result.is_success


def test_type_falls_back_with_caret_position(mock_ax, mock_ax_patterns):
    """Falls back when caret_position is not idle — SetValue can't position caret."""
    from operator_use.computer.tools.macos import computer

    element = MagicMock()
    mock_ax.ElementAtPosition.return_value = element
    mock_ax.GetRootControl.return_value = MagicMock()
    mock_ax_patterns.ValuePattern.IsSupported.return_value = True
    mock_ax_patterns.ValuePattern.return_value.IsReadOnly = False

    result = run(computer(action="type", loc=[100, 200], text="hello", caret_position="end"))

    mock_ax.Click.assert_called()
    mock_ax.TypeText.assert_called_once_with("hello")
    assert result.is_success


def test_type_press_enter_after_set_value(mock_ax, mock_ax_patterns):
    """press_enter=True fires KeyPress after SetValue."""
    from operator_use.computer.tools.macos import computer

    element = MagicMock()
    mock_ax.ElementAtPosition.return_value = element
    mock_ax.GetRootControl.return_value = MagicMock()

    value_pattern = MagicMock()
    value_pattern.IsReadOnly = False
    mock_ax_patterns.ValuePattern.IsSupported.return_value = True
    mock_ax_patterns.ValuePattern.return_value = value_pattern

    result = run(computer(action="type", loc=[100, 200], text="hello", press_enter=True))

    value_pattern.SetValue.assert_called_once_with("hello")
    mock_ax.KeyPress.assert_called_once_with(mock_ax.KeyCode.Return)
    assert result.is_success
```

**Step 2: Run to verify failures**

```bash
python -m pytest tests/test_cursorless_macos.py::test_type_uses_value_pattern_when_supported -v
```

Expected: FAIL — type action still calls `ax.Click`.

**Step 3: Implement**

Replace the `case "type":` block (lines 215–237) with:

```python
        case "type":
            if not loc:
                return ToolResult.error_result("loc is required for type.")
            if text is None:
                return ToolResult.error_result("text is required for type.")
            x, y = loc[0], loc[1]
            # Cursorless path: only when caret_position is idle (SetValue replaces all)
            if caret_position == "idle":
                try:
                    element = ax.ElementAtPosition(ax.GetRootControl(), x, y)
                    if element and ax_patterns.ValuePattern.IsSupported(element):
                        vp = ax_patterns.ValuePattern(element)
                        if not vp.IsReadOnly:
                            vp.SetValue(text)
                            if press_enter:
                                ax.KeyPress(ax.KeyCode.Return)
                            return ToolResult.success_result(f"Typed at ({x},{y}).")
                except Exception:
                    pass
            # Coordinate fallback
            ax.Click(x, y)
            await asyncio.sleep(0.05)
            if clear:
                ax.HotKey("command", "a")
                await asyncio.sleep(0.05)
                ax.KeyPress(ax.KeyCode.Delete)
            if caret_position == "start":
                ax.HotKey("command", "left")
                await asyncio.sleep(0.05)
            elif caret_position == "end":
                ax.HotKey("command", "right")
                await asyncio.sleep(0.05)
            ax.TypeText(text)
            if press_enter:
                await asyncio.sleep(0.05)
                ax.KeyPress(ax.KeyCode.Return)
            return ToolResult.success_result(f"Typed at ({x},{y}).")
```

**Step 4: Run all macOS tests**

```bash
python -m pytest tests/test_cursorless_macos.py -v
```

Expected: All 11 tests pass.

**Step 5: Commit**

```bash
git add operator_use/computer/tools/macos.py tests/test_cursorless_macos.py
git commit -m "feat(macos): cursorless type via ValuePattern.SetValue with coordinate fallback"
```

---

## Task 3: Windows — cursorless click

**Files:**
- Modify: `operator_use/computer/tools/windows.py` — `click` action block (lines 195–213)
- Create: `tests/test_cursorless_windows.py`

**Step 1: Write the failing tests**

```python
# tests/test_cursorless_windows.py
import pytest
from unittest.mock import MagicMock, patch
import asyncio


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


def test_click_uses_invoke_pattern_when_supported(mock_uia, mock_vdm):
    """Left single click should use InvokePattern and NOT call uia.Click."""
    from operator_use.computer.tools.windows import computer

    control = MagicMock()
    mock_uia.ControlFromPoint.return_value = control

    invoke = MagicMock()
    invoke.Invoke.return_value = True
    control.GetPattern.return_value = invoke

    result = run(computer(action="click", loc=[100, 200]))

    mock_uia.ControlFromPoint.assert_called_once_with(100, 200)
    invoke.Invoke.assert_called_once()
    mock_uia.Click.assert_not_called()
    assert result.is_success


def test_click_falls_back_when_no_invoke_pattern(mock_uia, mock_vdm):
    """Falls back to uia.Click when GetPattern returns None."""
    from operator_use.computer.tools.windows import computer

    control = MagicMock()
    mock_uia.ControlFromPoint.return_value = control
    control.GetPattern.return_value = None

    result = run(computer(action="click", loc=[100, 200]))

    mock_uia.Click.assert_called_once_with(100, 200)
    assert result.is_success


def test_click_falls_back_when_no_control(mock_uia, mock_vdm):
    """Falls back to uia.Click when ControlFromPoint returns None."""
    from operator_use.computer.tools.windows import computer

    mock_uia.ControlFromPoint.return_value = None

    result = run(computer(action="click", loc=[100, 200]))

    mock_uia.Click.assert_called_once_with(100, 200)
    assert result.is_success


def test_right_click_always_coordinate(mock_uia, mock_vdm):
    """Right click skips cursorless path entirely."""
    from operator_use.computer.tools.windows import computer

    result = run(computer(action="click", loc=[100, 200], button="right"))

    mock_uia.ControlFromPoint.assert_not_called()
    mock_uia.RightClick.assert_called_once_with(100, 200)
    assert result.is_success


def test_double_click_always_coordinate(mock_uia, mock_vdm):
    from operator_use.computer.tools.windows import computer

    result = run(computer(action="click", loc=[100, 200], clicks=2))

    mock_uia.ControlFromPoint.assert_not_called()
    mock_uia.DoubleClick.assert_called_once_with(100, 200)
    assert result.is_success


def test_invoke_exception_falls_back(mock_uia, mock_vdm):
    """Exception in Invoke() falls back silently."""
    from operator_use.computer.tools.windows import computer

    control = MagicMock()
    mock_uia.ControlFromPoint.return_value = control
    control.GetPattern.return_value.Invoke.side_effect = Exception("UIA error")

    result = run(computer(action="click", loc=[100, 200]))

    mock_uia.Click.assert_called_once_with(100, 200)
    assert result.is_success
```

**Step 2: Run to verify failures**

```bash
python -m pytest tests/test_cursorless_windows.py -v 2>&1 | head -20
```

Expected: FAIL — `uia.ControlFromPoint` not called from click action yet.

**Step 3: Implement**

In `operator_use/computer/tools/windows.py`, check what PatternId the UIA module uses for InvokePattern:

```bash
grep -n "InvokePattern\|PatternId" operator_use/computer/windows/uia/core.py | head -20
grep -n "class PatternId\|InvokePattern" operator_use/computer/windows/uia/enums.py | head -10
```

Then replace the `case "click":` block (lines 195–213) with:

```python
        case "click":
            if not loc:
                return ToolResult.error_result("loc is required for click.")
            x, y = loc[0], loc[1]
            if clicks == 0:
                uia.SetCursorPos(x, y)
                return ToolResult.success_result(f"Moved cursor to ({x},{y}).")
            # Cursorless path: only for left single clicks
            if button == "left" and clicks == 1:
                try:
                    control = uia.ControlFromPoint(x, y)
                    if control is not None:
                        invoke = control.GetPattern(uia.PatternId.InvokePattern)
                        if invoke is not None:
                            invoke.Invoke()
                            return ToolResult.success_result(f"Single left clicked at ({x},{y}).")
                except Exception:
                    pass
            # Coordinate fallback
            match button:
                case "left":
                    if clicks >= 2:
                        uia.DoubleClick(x, y)
                    else:
                        uia.Click(x, y)
                case "right":
                    uia.RightClick(x, y)
                case "middle":
                    uia.MiddleClick(x, y)
            labels = {1: "Single", 2: "Double", 3: "Triple"}
            return ToolResult.success_result(f"{labels.get(clicks, str(clicks))} {button} clicked at ({x},{y}).")
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_cursorless_windows.py -v
```

Expected: All 6 tests pass.

**Step 5: Commit**

```bash
git add operator_use/computer/tools/windows.py tests/test_cursorless_windows.py
git commit -m "feat(windows): cursorless click via InvokePattern with coordinate fallback"
```

---

## Task 4: Windows — cursorless type

**Files:**
- Modify: `operator_use/computer/tools/windows.py` — `type` action block (lines 215–234)
- Modify: `tests/test_cursorless_windows.py` — add type tests

**Step 1: Write the failing tests** (append to `tests/test_cursorless_windows.py`)

```python
def test_type_uses_value_pattern(mock_uia, mock_vdm):
    """Type should call ValuePattern.SetValue, not uia.Click or SendKeys."""
    from operator_use.computer.tools.windows import computer

    control = MagicMock()
    mock_uia.ControlFromPoint.return_value = control

    value_pattern = MagicMock()
    value_pattern.IsReadOnly = False

    def get_pattern(pattern_id):
        if pattern_id == mock_uia.PatternId.ValuePattern:
            return value_pattern
        return None

    control.GetPattern.side_effect = get_pattern

    result = run(computer(action="type", loc=[100, 200], text="hello"))

    value_pattern.SetValue.assert_called_once_with("hello")
    mock_uia.Click.assert_not_called()
    assert result.is_success


def test_type_falls_back_with_caret_position(mock_uia, mock_vdm):
    """Falls back when caret_position is not idle."""
    from operator_use.computer.tools.windows import computer

    control = MagicMock()
    mock_uia.ControlFromPoint.return_value = control
    control.GetPattern.return_value.IsReadOnly = False

    result = run(computer(action="type", loc=[100, 200], text="hello", caret_position="end"))

    mock_uia.Click.assert_called()
    assert result.is_success


def test_type_press_enter_after_set_value(mock_uia, mock_vdm):
    """press_enter fires SendKeys Enter after SetValue."""
    from operator_use.computer.tools.windows import computer

    control = MagicMock()
    mock_uia.ControlFromPoint.return_value = control
    value_pattern = MagicMock()
    value_pattern.IsReadOnly = False

    def get_pattern(pattern_id):
        if pattern_id == mock_uia.PatternId.ValuePattern:
            return value_pattern
        return None

    control.GetPattern.side_effect = get_pattern

    result = run(computer(action="type", loc=[100, 200], text="hello", press_enter=True))

    value_pattern.SetValue.assert_called_once_with("hello")
    mock_uia.SendKeys.assert_called_with("{Enter}", waitTime=0.05)
    assert result.is_success
```

**Step 2: Run to verify failures**

```bash
python -m pytest tests/test_cursorless_windows.py::test_type_uses_value_pattern -v
```

Expected: FAIL.

**Step 3: Implement**

Replace the `case "type":` block (lines 215–234) with:

```python
        case "type":
            if not loc:
                return ToolResult.error_result("loc is required for type.")
            if text is None:
                return ToolResult.error_result("text is required for type.")
            x, y = loc[0], loc[1]
            # Cursorless path: only when caret_position is idle
            if caret_position == "idle":
                try:
                    control = uia.ControlFromPoint(x, y)
                    if control is not None:
                        vp = control.GetPattern(uia.PatternId.ValuePattern)
                        if vp is not None and not vp.IsReadOnly:
                            vp.SetValue(text)
                            if press_enter:
                                uia.SendKeys("{Enter}", waitTime=0.05)
                            return ToolResult.success_result(f"Typed at ({x},{y}).")
                except Exception:
                    pass
            # Coordinate fallback
            uia.Click(x, y)
            if caret_position == "start":
                uia.SendKeys("{Home}", waitTime=0.05)
            elif caret_position == "end":
                uia.SendKeys("{End}", waitTime=0.05)
            if clear:
                await asyncio.sleep(0.5)
                uia.SendKeys("{Ctrl}a", waitTime=0.05)
                uia.SendKeys("{Back}", waitTime=0.05)
            escaped = uia._escape_text_for_sendkeys(text)
            uia.SendKeys(escaped, interval=0.01, waitTime=0.05)
            if press_enter:
                uia.SendKeys("{Enter}", waitTime=0.05)
            return ToolResult.success_result(f"Typed at ({x},{y}).")
```

**Step 4: Run all tests**

```bash
python -m pytest tests/test_cursorless_windows.py tests/test_cursorless_macos.py -v
```

Expected: All tests pass.

**Step 5: Run full test suite**

```bash
python -m pytest tests/ -v --ignore=tests/test_browser_e2e.py 2>&1 | tail -20
```

Expected: No regressions.

**Step 6: Commit**

```bash
git add operator_use/computer/tools/windows.py tests/test_cursorless_windows.py
git commit -m "feat(windows): cursorless type via ValuePattern.SetValue with coordinate fallback"
```

---

## Task 5: GitHub issue, PR, and future work tracking

**Step 1: Raise future-work GitHub issue on the fork**

```bash
cd /Users/richardsongunde/projects/Operator-Use
gh issue create \
  --repo richard-devbot/Operator-Use \
  --title "feat: agent workspace isolation — cooperative input, Agent Space, PiP monitor" \
  --label "enhancement" \
  --body "$(cat <<'EOF'
## Context

Cursorless UI automation (#cursorless PR) eliminates cursor conflicts for supported elements. This issue tracks the next layer of agent/user coexistence work.

## Future work items

### 1. Linux AT-SPI support
Add `pyatspi` as optional dependency. Implement `_find_element_atspi(x, y)` for GNOME/GTK apps. Wayland needs `ydotool` for input.

### 2. Cooperative input locking
Detect user mouse/keyboard activity via `CGEventTap` (macOS) / low-level hook (Windows). Queue agent actions when user is actively typing or clicking. Resume on idle. Prevents any residual conflicts when cursorless falls back to coordinate path.

### 3. Agent Space (macOS Spaces)
Subscribe to `NSWorkspaceActiveSpaceDidChangeNotification`. When agent opens an app, force it to Space 2 via `CGSMoveWindowsToManagedSpace` (private API) or AppleScript. User stays on Space 1.

### 4. Picture-in-picture agent monitor
Floating overlay (PySide6 / Electron) showing agent's active window in real time. User can observe without switching Space.

### 5. Windows virtual display (WindowsPC-MCP integration)
Integrate Parsec VDD virtual display for visual isolation on Windows. Port WindowsPC-MCP's `display/` and `confinement/` layers into Operator-Use as an optional Windows-only plugin.

## Reference
- Design doc: `docs/plans/2026-03-31-cursorless-ui-automation-design.md`
- Inspired by: https://github.com/ShikeChen01/WindowsPC-MCP
EOF
)"
```

**Step 2: Push branch and create PR**

```bash
# Get current branch name
BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Push to fork
git push origin "$BRANCH"

# Create PR
gh pr create \
  --repo richard-devbot/Operator-Use \
  --base main \
  --title "feat: cursorless UI automation — InvokePattern/ValuePattern dispatch on macOS and Windows" \
  --body "$(cat <<'EOF'
## Summary

- On macOS, `click` now tries `AXUIElementPerformAction(kAXPressAction)` before falling back to `CGEventPost`
- On macOS, `type` now tries `AXUIElementSetAttributeValue(kAXValueAttribute, text)` before falling back to click+TypeText
- Same pattern on Windows via `IUIAutomationInvokePattern::Invoke()` and `IUIAutomationValuePattern::SetValue()`
- Agent never moves the user's cursor or steals focus for elements that support the accessibility APIs
- Silent fallback for: right/double/middle click, drag, non-idle caret position, unsupported elements, any exception

## How it works

At action time, the OS accessibility API resolves the element under the given coordinates (`AXUIElementCopyElementAtPosition` / `IUIAutomation::ElementFromPoint`). If the element supports `InvokePattern`/`ValuePattern`, we use those. Otherwise we fall back to the existing coordinate path transparently.

No changes to `ax/`, `uia/`, `plugin.py`, or the tree layer.

## Test plan

- [ ] `pytest tests/test_cursorless_macos.py` — 11 tests, all pass
- [ ] `pytest tests/test_cursorless_windows.py` — 9 tests, all pass
- [ ] `pytest tests/` — no regressions in existing suite
- [ ] Manual: open TextEdit, run agent type action, verify cursor does not move
- [ ] Manual: click a button via agent while actively moving mouse — cursor stays in place

## Future work

Tracked in issue: agent workspace isolation (cooperative input, Agent Space, PiP monitor, Windows VDD)

🤖 Generated with [Claude Code](https://claude.ai/claude-code)
EOF
)"
```

---

## Verification Checklist

Before marking complete:

```bash
# All cursorless tests pass
python -m pytest tests/test_cursorless_macos.py tests/test_cursorless_windows.py -v

# No regressions
python -m pytest tests/ --ignore=tests/test_browser_e2e.py -q

# PR created
gh pr list --repo richard-devbot/Operator-Use
```
