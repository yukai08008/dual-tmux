from __future__ import annotations

from pathlib import Path

_UI_DIR = Path(__file__).resolve().parent
_COMPONENTS_DIR = _UI_DIR / "components"


def get_theme_css() -> str:
    """Return the unified design system CSS."""
    theme_file = _UI_DIR / "theme.css"
    if theme_file.exists():
        return theme_file.read_text(encoding="utf-8")
    return ""


def get_components_css() -> str:
    """Return aggregated CSS for all modular components."""
    parts = []
    if _COMPONENTS_DIR.exists():
        for path in sorted(_COMPONENTS_DIR.glob("*.css")):
            parts.append(f"/* === {path.name} === */\n" + path.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def get_components_js() -> str:
    """Return aggregated JS for all modular components."""
    parts = []
    if _COMPONENTS_DIR.exists():
        for path in sorted(_COMPONENTS_DIR.glob("*.js")):
            parts.append(f"/* === {path.name} === */\n" + path.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def get_unified_assets() -> dict[str, str]:
    """Return theme CSS, components CSS, and components JS."""
    return {
        "theme_css": get_theme_css(),
        "components_css": get_components_css(),
        "components_js": get_components_js(),
    }

