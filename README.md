# PhoneCluster Solo

> One phone. Full stack. Zero waste.

Everything from the multi-phone PhoneCluster - NAS, file sync, web dashboard,
metrics, and optional offsite backup - running on a single Android phone via
Termux + a real Arch Linux ARM rootfs.

---

## What runs on your phone

```
Termux (host)
|-- proot -> Arch Linux ARM rootfs
      |-- s6-svscan supervises:
            |-- caddy          :8080  - reverse proxy, all services behind clean paths
            |-- coordinator    :7777  - REST API + heartbeat tracker (internal)
            |-- filebrowser    :8081  - web file manager (internal -> /files)
            |-- syncthing      :8384  - LAN file sync   (internal -> /sync)
            |-- node-exporter  :9100  - Prometheus metrics (internal -> /metrics)
            |-- rclone                - offsite backup loop (optional)

Dashboard:    http://<phone-ip>:7000
All services: http://<phone-ip>:8080
```

The coordinator self-registers the node and sends its own heartbeat - no separate
agent needed for single-phone mode.

---

## Install

### 1. Install Termux + Termux:Boot

Get both from **F-Droid** (not the Play Store - the Play Store version is outdated).

- [Termux](https://f-droid.org/packages/com.termux/)
- [Termux:Boot](https://f-droid.org/packages/com.termux.boot/)

### 2. Clone and install

Open Termux and run:

```sh
pkg update && pkg install -y git
git clone https://github.com/yourname/phonecluster ~/phonecluster
cd ~/phonecluster
sh install.sh
```

**What the installer does:**
- Bootstraps Arch Linux ARM rootfs via `proot-distro` (first run only)
- Installs base packages (caddy, syncthing, rclone, node-exporter, python, etc.)
- Builds **s6**, **s6-rc**, and **execline** from source (these are not in Arch ARM repos)
- Downloads and installs **filebrowser** binary
- Deploys service definitions and configuration
- Sets up Termux:Boot startup script

**Note:** Building s6 from source takes **5-15 minutes** on the device. The installer will patch `proot-distro` for Termux compatibility automatically.

Answer two prompts:
- **Node name** - any short label, e.g. `my-phone`
- **API key** - used to authenticate dashboard and API requests

### 3. Disable battery optimisation

This is the single most important step. Without it, Android will kill your
services randomly within minutes.

```
Settings -> Apps -> Termux -> Battery -> Unrestricted
```

### 4. Start

```sh
sh ~/.termux/boot/start-cluster.sh
```

Or just reboot - Termux:Boot will start it automatically.

---

## Accessing your services

| Service | URL |
|---------|-----|
| Dashboard | `http://<phone-ip>:7000` |
| File Browser | `http://<phone-ip>:8080/files` |
| Syncthing | `http://<phone-ip>:8080/sync` |
| Metrics | `http://<phone-ip>:8080/metrics` |
| Health check | `http://<phone-ip>:8080/ping` |

Find your phone's IP: **Settings -> Wi-Fi -> tap your network -> IP address**

---

## Dashboard

Open `http://<phone-ip>:7000` on any device on your Wi-Fi.

Shows:
- Live CPU / memory / storage gauges
- Service status (Up/Down ping checks)
- Node registration and event log
- Auto-refreshes every 5-15 seconds

First time: click the gear icon ([GEAR] Config) and set the coordinator URL to
`http://<phone-ip>:7000` and your API key.

---

## Offsite backup (optional)

Edit `/etc/phonecluster/config.env` inside the rootfs:

```sh
proot-distro login archlinux
nano /etc/phonecluster/config.env
```

Set:
```sh
RCLONE_DEST=mys3:my-bucket          # any rclone remote
RCLONE_INTERVAL=3600                  # sync every hour
```

Then configure the rclone remote:
```sh
# inside rootfs
rclone config
```

The rclone s6 service will pick up the config on next restart and begin syncing
`/data/phonecluster/files` to your remote.

---

## Optional containers (MinIO, Gitea, etc.)

`phonecluster-run` lets you run OCI images via proot - no Docker daemon:

```sh
# Inside the rootfs - install skopeo + umoci first:
pacman -S skopeo umoci

# Run MinIO
phonecluster-run minio/minio \
    --name minio \
    --env MINIO_ROOT_USER=admin \
    --env MINIO_ROOT_PASSWORD=secret \
    -- server /data/minio

# Run Gitea
phonecluster-run gitea/gitea \
    --name gitea \
    --port 3000:3000
```

Then add a Caddy route in `/etc/caddy/Caddyfile` to expose it:

```
handle /git* {
    uri strip_prefix /git
    reverse_proxy 127.0.0.1:3000
}
```

Reload Caddy: `s6-svc -h /run/service/caddy`

---

## Updating config

All config lives in `/etc/phonecluster/config.env` inside the rootfs.
Edit it and restart the affected service:

```sh
proot-distro login archlinux

# Edit
nano /etc/phonecluster/config.env

# Restart a specific service (e.g. rclone)
s6-svc -r /run/service/rclone

# Restart everything
s6-svscanctl -r /run/service
```

---

## Project layout

```
phonecluster/
|-- install.sh               # Interactive installer
|-- bootstrap-rootfs.sh      # proot-distro Arch ARM bootstrap
|-- bin/
|   |-- phonecluster-run     # proot OCI container shim
|-- boot/
|   |-- start-cluster.sh     # Termux:Boot watchdog entry point
|-- config/
|   |-- Caddyfile.solo       # Reverse proxy config template
|-- coordinator/
|   |-- coordinator.py       # Flask API (self-registers in solo mode)
|-- dashboard/
|   |-- index.html           # Single-file dashboard with live metrics
|-- services/                # s6 service run scripts
    |-- caddy/run
    |-- coordinator/run
    |-- syncthing/run
    |-- filebrowser/run
    |-- node-exporter/run
    |-- rclone/run
```

---

## Troubleshooting

**Services die after a few minutes**
-> Battery optimisation for Termux is still enabled. Disable it (see Install step 3).

**Dashboard says "Coordinator offline"**
-> Check `~/phonecluster-boot.log` for proot session errors.
-> Manually test: `proot-distro login archlinux -- curl http://127.0.0.1:7777/health`

**Caddy 403 / 404 on /files or /sync**
-> The upstream service may not have started yet. Check s6 status inside rootfs:
   `s6-svstat /run/service/*`

**Syncthing won't open in browser**
-> Syncthing binds to `127.0.0.1:8384` by default. Caddy proxies it at `/sync`.
-> On first run, Syncthing needs to be configured - go to `http://<ip>:8080/sync`
   and follow its web UI.

**proot-distro install fails**
-> Make sure storage is not full: `df -h`
-> Try: `pkg reinstall proot-distro`

**s6/filebrowser package not found**
-> These are built from source; the installer handles this automatically.
-> Ensure `base-devel` is installed (`pacman -S base-devel` inside rootfs) if building manually.

**Install takes too long / hangs on s6 build**
-> Building s6, execline, and s6-rc can take 5-15 minutes depending on device speed.
-> This is normal; let it run. Monitor with `tail -f ~/phonecluster-boot.log` if needed.
