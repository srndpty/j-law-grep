#!/usr/bin/env sh
# wait-for.sh host:port -- command args

set -e

HOSTPORT=$1
shift

HOST=$(printf "%s" "$HOSTPORT" | cut -d: -f1)
PORT=$(printf "%s" "$HOSTPORT" | cut -d: -f2)

while ! nc -z "$HOST" "$PORT"; do
  echo "Waiting for $HOSTPORT..."
  sleep 1
done

exec "$@"
