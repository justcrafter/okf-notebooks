#!/bin/sh
# HOME=/tmp is a tmpfs, so the global git config is rebuilt on every start.
set -eu
if ! git config --global --get-all safe.directory | grep -qx /data; then
  git config --global --add safe.directory /data
fi
exec okf-notebooks "$@"
