#!/usr/bin/env bash
set -euo pipefail

if [[ -t 1 ]]; then
    GREEN=$'\033[32m'
    RESET=$'\033[0m'
else
    GREEN=""
    RESET=""
fi

echo
printf '%s' "$GREEN"
cat <<'BANNER'
 _ .-') _                .-') _                          .-')
( (  OO) )              ( OO ) )                        ( OO ).
 \     .'_   ,-.-') ,--./ ,--,'  ,----.    ,--. ,--.   (_)---\_)
 ,`'--..._)  |  |OO)|   \ |  |\ '  .-./-') |  | |  |   /    _ |
 |  |  \  '  |  |  \|    \|  | )|  |_( O- )|  | | .-') \  :` `.
 |  |   ' |  |  |(_/|  .     |/ |  | .--, \|  |_|( OO ) '..`''.)
 |  |   / : ,|  |_.'|  |\    | (|  | '. (_/|  | | `-' /.-._)   \
 |  '--'  /(_|  |   |  | \   |  |  '--'  |('  '-'(_.-' \       /
 `-------'   `--'   `--'  `--'   `------'   `-----'     `-----'
BANNER
printf '%s\n' "$RESET"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/dingus.py"
DESKTOP_SRC="$SCRIPT_DIR/dingus.desktop"
ICONS_SRC="$SCRIPT_DIR/icons"
BIN_DIR="$HOME/.local/bin"
DEST="$BIN_DIR/dingus"
APPS_DIR="$HOME/.local/share/applications"
HICOLOR_DIR="$HOME/.local/share/icons/hicolor"

if [[ ! -f "$SRC" ]]; then
    echo "Error: $SRC not found" >&2
    exit 1
fi

if [[ ! -d "$BIN_DIR" ]]; then
    echo "Creating $BIN_DIR"
    mkdir -p "$BIN_DIR"
fi

echo "Installing dingus to $DEST"
install -m 755 "$SRC" "$DEST"

if [[ -d "$ICONS_SRC" ]]; then
    for size_dir in "$ICONS_SRC"/*/; do
        [[ -d "$size_dir" ]] || continue
        size=$(basename "$size_dir")
        target_dir="$HOME/.local/share/icons/hicolor/$size/apps"
        mkdir -p "$target_dir"
        for icon in "$size_dir"*; do
            [[ -f "$icon" ]] || continue
            target="$target_dir/$(basename "$icon")"
            echo "Installing icon to $target"
            install -m 644 "$icon" "$target"
        done
    done
    gtk-update-icon-cache "$HICOLOR_DIR" 2>/dev/null || true
fi

if [[ -f "$DESKTOP_SRC" ]]; then
    if [[ ! -d "$APPS_DIR" ]]; then
        echo "Creating $APPS_DIR"
        mkdir -p "$APPS_DIR"
    fi
    echo "Installing desktop entry to $APPS_DIR/dingus.desktop"
    install -m 644 "$DESKTOP_SRC" "$APPS_DIR/dingus.desktop"
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi

case ":$PATH:" in
    *":$BIN_DIR:"*)
        echo "$BIN_DIR is already in PATH"
        ;;
    *)
        SHELL_NAME="$(basename "${SHELL:-}")"
        case "$SHELL_NAME" in
            bash)
                RC="$HOME/.bashrc"
                PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
                if [[ -f "$RC" ]] && grep -Fq "$PATH_LINE" "$RC"; then
                    echo "PATH line already present in $RC (open a new shell or 'source $RC')"
                else
                    echo "Appending PATH line to $RC"
                    printf '\n# Added by dingus install.sh\n%s\n' "$PATH_LINE" >> "$RC"
                    echo "Run 'source $RC' or open a new shell to pick it up."
                fi
                ;;
            zsh)
                RC="${ZDOTDIR:-$HOME}/.zshrc"
                PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
                if [[ -f "$RC" ]] && grep -Fq "$PATH_LINE" "$RC"; then
                    echo "PATH line already present in $RC (open a new shell or 'source $RC')"
                else
                    echo "Appending PATH line to $RC"
                    printf '\n# Added by dingus install.sh\n%s\n' "$PATH_LINE" >> "$RC"
                    echo "Run 'source $RC' or open a new shell to pick it up."
                fi
                ;;
            fish)
                if command -v fish >/dev/null 2>&1; then
                    echo "Adding $BIN_DIR to fish_user_paths"
                    fish -c "fish_add_path -g $BIN_DIR"
                    echo "Open a new fish shell to pick it up."
                else
                    echo "fish not found in PATH; add manually with: fish_add_path $BIN_DIR"
                fi
                ;;
            *)
                echo "Unrecognized shell: $SHELL_NAME"
                echo "Add this line to your shell's rc file manually:"
                echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
                ;;
        esac
        ;;
esac

echo
printf '%sDone.%s Run: dingus\n' "$GREEN" "$RESET"
echo
echo "Notes:"
echo "  - On GNOME, install the AppIndicator extension for the tray icon to show:"
echo "    https://extensions.gnome.org/extension/615/appindicator-support/"
echo "  - Toggle 'Auto-start' from the tray menu to run dingus on login."
echo "  - Edit your config via the tray's 'Settings' entry (or ~/.config/dingus/config.toml)."
echo
