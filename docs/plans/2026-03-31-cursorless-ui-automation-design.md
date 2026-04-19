# Cursorless UI Tree Automation — Design

**Date:** 2026-03-31
**Author:** Richardson Gunde
**Status:** Approved, ready for implementation

---

## Problem

Every desktop action the agent takes today physically moves the user's cursor and steals keyboard focus.
`ax.Click(x, y)` posts a `CGEventPost(kCGHIDEventTap, ...)` — a hardware-level mouse event.
`ax.TypeText(text)` posts `CGEventCreateKeyboardEvent` pairs — hardware keystrokes that require focus.

The agent and user fight for the same cursor. The user cannot work while the agent is running.

---

## Solution

Use the OS accessibility API to invoke elements directly — no cursor movement, no focus steal.

- **macOS:** `AXUIElementPerformAction(element, kAXPressAction)` and `AXUIElementSetAttributeValue(element, kAXValueAttribute, text)`
- **Windows:** `IUIAutomationInvokePattern::Invoke()` and `IUIAutomationValuePattern::SetValue()`

Both APIs are already implemented in `ax/patterns.py` (`InvokePattern`, `ValuePattern`) and `uia/patterns.py`. The only missing piece is wiring them into the tool action handlers.

---

## Architecture

### Element resolution at action time

Rather than tracking tree state across the tool boundary, resolve the element directly from screen coordinates using existing OS APIs:

- **macOS:** `ax.ElementAtPosition(ax.GetRootControl(), x, y)` — wraps `AXUIElementCopyElementAtPosition`, already in `ax/core.py:442`
- **Windows:** `uia.ControlFromPoint(x, y)` — wraps `IUIAutomation::ElementFromPoint`, already in `uia/controls.py:4345`

No module-level state. No tree cache. No bounding box matching. The OS returns the exact element under the coordinates in one call.

### Dispatch flow

```
click(loc=[x, y], button="left", clicks=1)
        │
        ▼
get element at (x, y) via OS accessibility API
        │
        ├─ element found?
        │   ├─ InvokePattern supported?  →  Invoke()  ← no cursor, no focus
        │   └─ not supported             →  fall back to CGEventPost / SendInput
        │
        └─ no element                    →  fall back to CGEventPost / SendInput

type(loc=[x, y], text="hello")
        │
        ▼
get element at (x, y) via OS accessibility API
        │
        ├─ element found?
        │   ├─ ValuePattern supported AND not ReadOnly?
        │   │   └─ SetValue(text)  ← no click, no focus steal
        │   └─ not supported / ReadOnly  →  fall back to click + TypeText
        │
        └─ no element                    →  fall back to click + TypeText
```

### Fallback conditions (always use coordinate path)

| Condition | Reason |
|---|---|
| `button != "left"` | Right/middle click needs screen position for context menus |
| `clicks != 1` | Double-click semantics (file open, text select) need coordinate events |
| `drag == True` | Drag requires hardware mouse events |
| `caret_position != "idle"` | SetValue replaces entire value; caret positioning needs keyboard events |
| Element not found at position | Canvas, custom/native widget, WebGL surface |
| Pattern not supported | Element doesn't implement InvokePattern/ValuePattern |
| Pattern invocation raises | Broken app, permission issue — degrade gracefully |

---

## Files Changed

### `operator_use/computer/tools/macos.py`

- `click` action: resolve element → try `InvokePattern.Invoke()` → fall back to `ax.Click()`
- `type` action: resolve element → try `ValuePattern.SetValue()` → fall back to `ax.Click()` + `ax.TypeText()`

### `operator_use/computer/tools/windows.py`

- Same pattern using `uia.ControlFromPoint(x, y)` and `uia.PatternId.InvokePattern` / `uia.PatternId.ValuePattern`

No changes to `ax/`, `uia/`, `plugin.py`, `desktop/`, or `tree/`.

---

## Unchanged

- `scroll` — wheel events are inherently coordinate-based
- `move` — cursor movement is the entire point
- `shortcut` — keyboard shortcuts are global by definition
- `drag` — requires hardware mouse hold
- Linux — stays on `xdotool` (no accessibility tree)

---

## Future Work (tracked in GitHub issues)

1. **Linux AT-SPI support** — Add `pyatspi` as optional dependency, implement `_find_element_atspi(x, y)` for GNOME/GTK apps
2. **Cooperative input locking** — Detect user mouse/keyboard activity and queue agent actions to avoid overlap
3. **Agent Space (macOS Spaces)** — Force agent-opened apps to Space 2 via `NSWorkspaceActiveSpaceDidChangeNotification`
4. **Picture-in-picture monitor** — Floating overlay showing agent screen state in real time
5. **Windows virtual desktop confinement** — Integrate WindowsPC-MCP's Parsec VDD approach for visual isolation on Windows
