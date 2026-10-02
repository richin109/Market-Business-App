#!/bin/sh
set -eu

for configuration in pyproject.toml uv.lock Dockerfile; do
    if ! cmp -s "/app/$configuration" "/opt/mbs-test-config/$configuration"; then
        printf '%s\n' "Test image configuration is stale ($configuration). Run: docker compose build test" >&2
        exit 1
    fi
done

mkdir -p "$HOME/.cache/mbs-test"
if [ ! -w /tmp/mbs-test-cache ]; then
    export RUFF_CACHE_DIR="$HOME/.cache/mbs-test/ruff"
    export MYPY_CACHE_DIR="$HOME/.cache/mbs-test/mypy"
    export PYTEST_ADDOPTS="-o cache_dir=$HOME/.cache/mbs-test/pytest --basetemp=/tmp/mbs-test-work/pytest --output=/tmp/mbs-test-work/playwright"
fi

exec "$@"