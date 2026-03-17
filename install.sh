#!/data/data/com.termux/files/usr/bin/sh
# PhoneCluster Solo - single-phone installer
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
                          [ SOLO - single phone edition ]
BANNER
echo ""

###############################################################################
# Checks
###############################################################################

[ -d "$PREFIX" ] || die "Must run inside Termux."
command -v proot-distro >/dev/null 2>&1 || pkg install -y proot-distro
command -v python      >/dev/null 2>&1 || pkg install -y python

# Ensure proot-distro works under Termux: it erroneously blocks ANY proot tracer.
# Patch the check to only block nested proot-distro (the intended behavior).
info "Configuring proot-distro for Termux..."
sed -i 's/if \[ "$TRACER_NAME" = "proot" \]/if [ "$TRACER_NAME" = "proot-distro" ]/' /data/data/com.termux/files/usr/bin/proot-distro 2>/dev/null || true

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
# Install base packages (those available in repos)
###############################################################################

info "Installing base packages..."
proot-distro login archlinux -- pacman -Sy --noconfirm --needed \
    base-devel \
    caddy \
    syncthing \
    rclone \
    prometheus-node-exporter \
    python python-pip \
    curl wget jq \
    procps-ng iproute2 \
    git

proot-distro login archlinux -- \
    pip install flask --break-system-packages --quiet

###############################################################################
# Build and install skalibs, s6, s6-rc, execline from source (not in Arch ARM repos)
###############################################################################

info "Building s6 suite from source (this may take 5-10 minutes)..."
proot-distro login archlinux -- sh -c '
    set -e
    TMPDIR=$(mktemp -d)
    cd "$TMPDIR"
    MAKEFLAGS="-j$(nproc)"

    # skalibs (common dependency)
    echo "Downloading skalibs..."
    curl -sL https://github.com/skarnet/skalibs/releases/download/2.14.1.0/skalibs-2.14.1.0.tar.gz | tar xz
    cd skalibs-*
    ./configure --prefix=/usr && make $MAKEFLAGS && make install
    cd "$TMPDIR"

    # s6
    echo "Downloading s6..."
    curl -sL https://github.com/skarnet/s6/releases/download/v2.12.0.0/s6-2.12.0.0.tar.gz | tar xz
    cd s6-*
    ./configure --prefix=/usr && make $MAKEFLAGS && make install
    cd "$TMPDIR"

    # execline
    echo "Downloading execline..."
    curl -sL https://github.com/skarnet/execline/releases/download/v2.9.5.0/execline-2.9.5.0.tar.gz | tar xz
    cd execline-*
    ./configure --prefix=/usr && make $MAKEFLAGS && make install
    cd "$TMPDIR"

    # s6-rc
    echo "Downloading s6-rc..."
    curl -sL https://github.com/skarnet/s6-rc/releases/download/v0.5.4.0/s6-rc-0.5.4.0.tar.gz | tar xz
    cd s6-rc-*
    ./configure --prefix=/usr && make $MAKEFLAGS && make install
    cd "$TMPDIR"

    rm -rf "$TMPDIR"
    echo "s6 suite installed to /usr"
'

###############################################################################
# Install filebrowser (download binary)
###############################################################################

info "Installing filebrowser..."
proot-distro login archlinux -- sh -c '
    set -e
    FILEBROWSER_VERSION="2.28.0"
    ARCH="aarch64"
    curl -sL "https://github.com/filebrowser/filebrowser/releases/download/v${FILEBROWSER_VERSION}/filebrowser-${FILEBROWSER_VERSION}-linux-${ARCH}.tar.gz" | tar xz -C /usr/local/bin
    chmod +x /usr/local/bin/filebrowser
    ln -sf /usr/local/bin/filebrowser /usr/bin/filebrowser
    echo "filebrowser installed"
'

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
echo "  +-------------------------------------------------+"
echo "  |  Dashboard      http://$LOCAL_IP:7000          |"
echo "  |  Files          http://$LOCAL_IP:8080/files    |"
echo "  |  Syncthing      http://$LOCAL_IP:8080/sync     |"
echo "  |  Metrics        http://$LOCAL_IP:8080/metrics  |"
echo "  +-------------------------------------------------+"
echo ""
warn "ACTION: Disable battery optimisation for Termux"
warn "  Settings -> Apps -> Termux -> Battery -> Unrestricted"
echo ""
echo "  Start now:  sh $BOOT_DIR/start-cluster.sh"
echo ""
