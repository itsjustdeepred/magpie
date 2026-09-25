#!/bin/sh
# Started as root: hand /data to PUID:PGID (older releases wrote it as root)
# and drop privileges. Started with --user: run as that user unchanged.
set -e
if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    chown -R "$PUID:$PGID" "$DATA_DIR"
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
fi
exec "$@"
