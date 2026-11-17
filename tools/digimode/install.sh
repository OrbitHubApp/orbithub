#!/bin/sh
# OrbitHub Digimode-Dienst einrichten (ohne sudo).
# Holt die WSJT-X-Decoder (jt9, wsprd, ...) als Debian-Paket und entpackt sie
# nur nach ~/digimode/pkg - es wird nichts systemweit installiert.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DIR="$HOME/digimode/pkg"
mkdir -p "$DIR"
cd "$DIR"
rm -f ./*.deb
apt-get download wsjtx libgfortran5
for deb in ./*.deb; do dpkg -x "$deb" root; done
LIB=$(dirname "$(find "$DIR/root" -name 'libgfortran.so.5*' | head -1)")
LD_LIBRARY_PATH="$LIB" "$DIR/root/usr/bin/jt9" -h >/dev/null 2>&1 || true
echo "Decoder: $DIR/root/usr/bin (Bibliotheken: $LIB)"
mkdir -p "$HOME/.config/systemd/user"
cp "$SRC/digimode.service" "$HOME/.config/systemd/user/"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
systemctl --user daemon-reload
systemctl --user enable --now digimode.service
systemctl --user --no-pager status digimode.service | head -5
