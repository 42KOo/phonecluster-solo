#!/data/data/com.termux/files/usr/bin/sh
# ~/.termux/boot/start-cluster.sh
# Launched by Termux:Boot on device startup.

LOG="$HOME/phonecluster-boot.log"
RETRY=0
MAX_RETRIES=20

# Prevent Android Doze from freezing the process
termux-wake-lock

termux-notification \
    --id phonecluster \
    --title "PhoneCluster" \
    --content "Starting..." \
    --ongoing --priority high 2>/dev/null || true

while true; do
    RETRY=$((RETRY + 1))
    echo "$(date): boot attempt $RETRY" >> "$LOG"

    termux-notification \
        --id phonecluster \
        --title "PhoneCluster" \
        --content "Running (started $(date +%H:%M))" \
        --ongoing --priority high 2>/dev/null || true

    # s6-svscan is PID 1 inside the rootfs — supervises all services
    proot-distro login archlinux -- /usr/bin/s6-svscan /run/service >> "$LOG" 2>&1

    CODE=$?
    echo "$(date): session exited (code $CODE)" >> "$LOG"

    [ $RETRY -ge $MAX_RETRIES ] && {
        termux-notification \
            --id phonecluster \
            --title "PhoneCluster STOPPED" \
            --content "Gave up after $MAX_RETRIES attempts. See ~/phonecluster-boot.log" \
            --priority high 2>/dev/null || true
        break
    }

    # Exponential backoff capped at 60s
    WAIT=$(( 5 * (1 << (RETRY < 5 ? RETRY - 1 : 4)) ))
    echo "$(date): retry in ${WAIT}s" >> "$LOG"
    sleep "$WAIT"
done
