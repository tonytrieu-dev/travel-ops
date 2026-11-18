#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")/.."
if [ -L .identity-provisioning ]; then
    printf '%s\n' 'Provisioning directory must not be a symbolic link' >&2
    exit 1
fi
install -d -m 700 .identity-provisioning
exec docker compose -f compose.zero-trust.yml run --rm \
    --user "$(id -u):$(id -g)" enroll "$@"
