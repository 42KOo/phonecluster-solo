#!/data/data/com.termux/files/usr/bin/sh
# PhoneCluster Solo — single-phone installer
set -e

PC_DIR="$HOME/phonecluster-solo"
ROOTFS_DIR="$PREFIX/var/lib/proot-distro/installed-rootfs/archlinux"
BOOT_DIR="$HOME/.termux/boot"

info()  { printf '\033[1;34m[INFO]\033[0m  %s\n' "$*"; }
ok()    { printf '\033[1;32m[ OK ]\033[0m  %s\n' "$*"; }
warn()  { printf '\033[1;33m[WARN]\033[0m  %s\n' "$*"; }
die()   { printf '\033[1;31m[ERR ]\033[0m  %s\n' "$*" >&2; exit 1; }

cat <<'BANNER'
 ____  _                      _____ _           _
|  _ \| |__   ___  _ __   ___/ ____| |_   _ ___| |_ ___ _ __
| |_) | '_ \ / _ \| '_ \ / _ \___ \| | | | / __| __/ _ \ '__|
|  __/| | | | (_) | | | |  __/___) | | |_| \__ \ ||  __/ |
|_|   |_| |_|\___/|_| |_|\___|____/|_|\__,_|___/\__\___|_|
                          [ SOLO — single phone edition ]
BANNER
echo ""

###############################################################################
# Checks
###############################################################################

[ -d "$PREFIX" ] || die "Must run inside Termux."
command -v proot-distro >/dev/null 2>&1 || pkg install -y proot-distro
command -v python      >/dev/null 2>&1 || pkg install -y python

###############################################################################
# Node ID
###############################################################################

printf "Enter a name for this node (e.g. my-phone): "
read -r NODE_ID
[ -n "$NODE_ID" ] || NODE_ID="solo-node"

###############################################################################
# API key
###############################################################################

printf "Set an API key for the dashboard [default: changeme]: "
read -r API_KEY
[ -n "$API_KEY" ] || API_KEY="changeme"

###############################################################################
# Bootstrap rootfs
###############################################################################

info "Bootstrapping Arch Linux ARM rootfs..."
sh "$PC_DIR/bootstrap-rootfs.sh"

###############################################################################
# Install all packages
###############################################################################

info "Installing packages..."
proot-distro login archlinux -- pacman -Sy --noconfirm --needed \
    s6 s6-rc execline \
    caddy \
    syncthing \
    filebrowser \
    rclone \
    prometheus-node-exporter \
    python python-pip \
    curl wget jq \
    procps-ng iproute2

proot-distro login archlinux -- \
    pip install flask --break-system-packages --quiet

###############################################################################
# Data dirs inside rootfs
###############################################################################

proot-distro login archlinux -- sh -c '
    mkdir -p /data/phonecluster/{files,syncthing,minio}
    mkdir -p /var/log/phonecluster
    mkdir -p /etc/phonecluster
    mkdir -p /etc/caddy
    mkdir -p /opt/coordinator
    mkdir -p /opt/dashboard
    mkdir -p /run/service
'

###############################################################################
# Write config
###############################################################################

info "Writing config..."
proot-distro login archlinux -- sh -c "cat > /etc/phonecluster/config.env" <<CONF
NODE_ID=$NODE_ID
NODE_ROLE=solo
COORDINATOR_IP=127.0.0.1
COORDINATOR_PORT=7000
PC_API_KEY=$API_KEY
DATA_DIR=/data/phonecluster
LOG_DIR=/var/log/phonecluster
RCLONE_SRC=/data/phonecluster/files
RCLONE_DEST=remote:phonecluster-backup
RCLONE_INTERVAL=3600
CONF
ok "Config written."

###############################################################################
# Install s6 service tree
###############################################################################

info "Installing s6 service tree..."
for svc in "$PC_DIR/services"/*/; do
    svc_name="$(basename "$svc")"
    dest="$ROOTFS_DIR/run/service/$svc_name"
    cp -r "$svc" "$dest"
    chmod +x "$dest/run"
    [ -f "$dest/finish" ] && chmod +x "$dest/finish"
    ok "  s6: $svc_name"
done

###############################################################################
# Coordinator + dashboard
###############################################################################

info "Installing coordinator..."
cp "$PC_DIR/coordinator/coordinator.py" "$ROOTFS_DIR/opt/coordinator/"

info "Installing dashboard..."
cp "$PC_DIR/dashboard/index.html" "$ROOTFS_DIR/opt/dashboard/"

###############################################################################
# Caddy config
###############################################################################

info "Generating Caddyfile..."
sed "s|{{NODE_ID}}|$NODE_ID|g" \
    "$PC_DIR/config/Caddyfile.solo" \
    > "$ROOTFS_DIR/etc/caddy/Caddyfile"
ok "Caddyfile written."

###############################################################################
# Termux:Boot
###############################################################################

info "Installing boot script..."
mkdir -p "$BOOT_DIR"
cp "$PC_DIR/boot/start-cluster.sh" "$BOOT_DIR/start-cluster.sh"
chmod +x "$BOOT_DIR/start-cluster.sh"

###############################################################################
# Done
###############################################################################

LOCAL_IP="$(ip route get 1 2>/dev/null | awk '{print $7; exit}' || echo 'YOUR-IP')"

echo ""
ok "PhoneCluster Solo installation complete!"
echo ""
echo "  ┌─────────────────────────────────────────────────┐"
echo "  │  Dashboard      http://$LOCAL_IP:7000          │"
echo "  │  Files          http://$LOCAL_IP:8080/files    │"
echo "  │  Syncthing      http://$LOCAL_IP:8080/sync     │"
echo "  │  Metrics        http://$LOCAL_IP:8080/metrics  │"
echo "  └─────────────────────────────────────────────────┘"
echo ""
warn "ACTION: Disable battery optimisation for Termux"
warn "  Settings → Apps → Termux → Battery → Unrestricted"
echo ""
echo "  Start now:  sh $BOOT_DIR/start-cluster.sh"
echo ""
