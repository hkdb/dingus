#!/usr/bin/env bash
set -euo pipefail

if [[ -t 1 ]]; then
    GREEN=$'\033[32m'
    YELLOW=$'\033[33m'
    RESET=$'\033[0m'
else
    GREEN=""
    YELLOW=""
    RESET=""
fi

echo
printf '%s' "$YELLOW"
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
                          uninstall
BANNER
printf '%s\n' "$RESET"

BIN_DIR="$HOME/.local/bin"
DEST="$BIN_DIR/dingus"
APPS_DIR="$HOME/.local/share/applications"
DESKTOP_DEST="$APPS_DIR/dingus.desktop"
HICOLOR_DIR="$HOME/.local/share/icons/hicolor"
AUTOSTART_DEST="$HOME/.config/autostart/dingus.desktop"

if pgrep -x dingus >/dev/null 2>&1; then
    echo "Stopping running dingus process"
    pkill -x dingus 2>/dev/null || true
fi

if [[ -f "$DEST" ]]; then
    echo "Removing $DEST"
    rm -f "$DEST"
fi

if [[ -d "$HICOLOR_DIR" ]]; then
    for size_dir in "$HICOLOR_DIR"/*/apps; do
        [[ -d "$size_dir" ]] || continue
        for pattern in dingus.svg dingus.png dingus-muted.svg dingus-muted.png; do
            target="$size_dir/$pattern"
            if [[ -f "$target" ]]; then
                echo "Removing icon $target"
                rm -f "$target"
            fi
        done
    done
    gtk-update-icon-cache "$HICOLOR_DIR" 2>/dev/null || true
fi

if [[ -f "$DESKTOP_DEST" ]]; then
    echo "Removing $DESKTOP_DEST"
    rm -f "$DESKTOP_DEST"
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi

if [[ -f "$AUTOSTART_DEST" ]]; then
    echo "Removing $AUTOSTART_DEST"
    rm -f "$AUTOSTART_DEST"
fi

echo
printf '%sDone.%s\n' "$GREEN" "$RESET"
echo
echo "Notes:"
echo "  - Config preserved at ~/.config/dingus/ (remove manually if desired)"
echo "  - Logs preserved at ~/.cache/dingus/ (remove manually if desired)"
echo "  - PATH line in your shell's rc file was not removed (other tools may rely on ~/.local/bin)"
echo
