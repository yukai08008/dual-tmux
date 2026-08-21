#!/usr/bin/env bash
set -euo pipefail

REPO="yukai08008/dual-tmux"
TOOL_NAME="dual-tmux"
BIN_NAME="dt"
INSTALL_DIR="${HOME}/.local/bin"
PACKAGE_SPEC="git+https://github.com/${REPO}.git"

info()  { printf '[dual-tmux] %s\n' "$*"; }
warn()  { printf '[dual-tmux] %s\n' "$*" >&2; }
error() { printf '[dual-tmux] %s\n' "$*" >&2; exit 1; }

ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        return
    fi
    info "uv not found; installing from astral.sh..."
    curl -fL --connect-timeout 10 --max-time 120 --retry 3 --progress-bar \
        https://astral.sh/uv/install.sh | sh
    export PATH="${INSTALL_DIR}:${PATH}"
    command -v uv >/dev/null 2>&1 || error "uv installation failed"
}

ensure_path() {
    mkdir -p "$INSTALL_DIR"
    case ":${PATH}:" in
        *:"${INSTALL_DIR}":*) return ;;
    esac
    local rc_file="${HOME}/.profile"
    if [ -n "${ZSH_VERSION:-}" ]; then
        rc_file="${HOME}/.zshrc"
    elif [ -n "${BASH_VERSION:-}" ]; then
        rc_file="${HOME}/.bashrc"
    fi
    warn "Adding ${INSTALL_DIR} to PATH in ${rc_file}"
    printf '\nexport PATH="%s:$PATH"\n' "$INSTALL_DIR" >> "$rc_file"
    export PATH="${INSTALL_DIR}:${PATH}"
}

install_or_update() {
    local action="$1"
    info "${action} dual-tmux from github.com/${REPO}..."
    uv tool install --force "$PACKAGE_SPEC"
    if command -v "$BIN_NAME" >/dev/null 2>&1; then
        info "Ready: $($BIN_NAME --version | sed -n '1p')"
        info "Next: dt config --init --client <id> --server <ssh-host> && dt doctor"
    elif [ -x "${INSTALL_DIR}/${BIN_NAME}" ]; then
        warn "Installed. Restart the terminal so ${INSTALL_DIR} is in PATH."
    else
        error "Installation failed."
    fi
}

uninstall() {
    if command -v uv >/dev/null 2>&1; then
        uv tool uninstall "$TOOL_NAME" 2>/dev/null || true
    fi
    rm -f "${INSTALL_DIR}/${BIN_NAME}"
    info "Uninstalled. Data under ~/.dual-tmux was preserved."
}

main() {
    case "${1:-install}" in
        install|update|upgrade)
            ensure_uv
            ensure_path
            install_or_update "Installing"
            ;;
        uninstall)
            uninstall
            ;;
        *)
            error "Usage: install.sh [install|update|uninstall]"
            ;;
    esac
}

main "$@"
