#!/bin/sh
# Curator installer.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/JasonZQH/CURATOR/main/install.sh | sh
#
# Optional environment variables:
#   CURATOR_REF   git ref (tag/branch) to install, e.g. v0.1.0 (default: main)
#
# This script bootstraps `uv` (which can manage its own Python) if it is not
# already present, then installs the `curator` CLI as a uv tool. It runs no
# code from the repository other than the standard package build.
set -eu

REPO="https://github.com/JasonZQH/CURATOR.git"
REF="${CURATOR_REF:-main}"

info() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
err() { printf '\033[1;31merror:\033[0m %s\n' "$1" >&2; }

if ! command -v uv >/dev/null 2>&1; then
  info "uv not found; installing uv..."
  curl -fsSL https://astral.sh/uv/install.sh | sh
  # Make uv available in this shell session.
  if [ -f "$HOME/.local/bin/env" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.local/bin/env"
  fi
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
  err "uv installation did not put 'uv' on PATH. Open a new shell and re-run."
  exit 1
fi

info "Installing Curator ($REF) with uv..."
uv tool install --force "git+${REPO}@${REF}"

info "Done. Verify with:  curator --version"
info "If 'curator' is not found, add uv's tool bin to PATH:  uv tool update-shell"
