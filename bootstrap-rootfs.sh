#!/data/data/com.termux/files/usr/bin/sh
# bootstrap-rootfs.sh - Bootstrap Arch Linux ARM via proot-distro
set -e

info() { printf '\033[1;34m[INFO]\033[0m  %s\n' "$*"; }
ok()   { printf '\033[1;32m[ OK ]\033[0m  %s\n' "$*"; }
die()  { printf '\033[1;31m[ERR ]\033[0m  %s\n' "$*" >&2; exit 1; }

ROOTFS="$PREFIX/var/lib/proot-distro/installed-rootfs/archlinux"

if [ -d "$ROOTFS/usr" ]; then
    ok "Rootfs already exists - skipping."
    exit 0
fi

info "Installing Arch Linux ARM via proot-distro..."
proot-distro install archlinux

[ -d "$ROOTFS/usr" ] || die "proot-distro install failed."

info "First-time rootfs init..."
proot-distro login archlinux -- sh -c '
    pacman -Sy --noconfirm archlinux-keyring 2>/dev/null || true
    pacman-key --init 2>/dev/null || true
    pacman-key --populate archlinux 2>/dev/null || true
    pacman -Syu --noconfirm
'

ok "Rootfs ready: $ROOTFS"
