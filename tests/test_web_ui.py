from __future__ import annotations

from dual_tmux.web_ui import (
    get_theme_css,
    get_components_css,
    get_components_js,
    get_unified_assets,
)


def test_web_ui_theme_loaded():
    css = get_theme_css()
    assert ":root" in css
    assert "--dt-primary" in css
    assert "--dt-bg-canvas" in css
    assert ".dt-btn" in css


def test_web_ui_components_css_loaded():
    css = get_components_css()
    assert "/* === terminal.css === */" in css
    assert "/* === sender.css === */" in css
    assert "/* === toast.css === */" in css
    assert "/* === picker.css === */" in css
    assert "/* === occupancy.css === */" in css
    assert "/* === lifecycle.css === */" in css
    assert "/* === thread.css === */" in css
    assert ".dt-scroll-lock-banner" in css


def test_web_ui_components_js_loaded():
    js = get_components_js()
    assert "class ToastManager" in js
    assert "class DualTerminalComponent" in js
    assert "class CommandSenderComponent" in js
    assert "class TunnelPickerComponent" in js
    assert "class OccupancyCardComponent" in js
    assert "class LifecycleToolbarComponent" in js
    assert "class TurnThreadComponent" in js
    assert "window.DualToast = new ToastManager()" in js


def test_web_ui_unified_assets():
    assets = get_unified_assets()
    assert len(assets["theme_css"]) > 500
    assert len(assets["components_css"]) > 1000
    assert len(assets["components_js"]) > 1000


def test_tunnel_picker_component_assets():
    js = get_components_js()
    css = get_components_css()
    assert "dt-focus-banner" in js
    assert "openNewTabPrompt" in js
    assert "isCreatingNewTab" in js
    assert "dt-focus-card" in css
    assert "dt-tab-item.active" in css
    assert "border-top: 3px solid var(--dt-primary)" in css
