#!/bin/bash
# Run OCA CI tests locally using the official OCA CI image (x86 emulation on Mac).
# Usage: ./run-tests-local.sh [ADDONS_TO_TEST]
#   ADDONS_TO_TEST: comma-separated list, e.g. "connector_amazon,connector_amazon_sale"
#                   Defaults to all addons in the repo.
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
NETWORK="amz-ci-local"
PG_CONTAINER="amz-ci-postgres"
OCA_IMAGE="ghcr.io/oca/oca-ci/py3.10-odoo19.0:latest"

cleanup() {
    docker rm -f "$PG_CONTAINER" 2>/dev/null || true
    docker network rm "$NETWORK" 2>/dev/null || true
}
trap cleanup EXIT

docker network create "$NETWORK" 2>/dev/null || true

docker rm -f "$PG_CONTAINER" 2>/dev/null || true
docker run -d \
    --name "$PG_CONTAINER" \
    --network "$NETWORK" \
    -e POSTGRES_USER=odoo \
    -e POSTGRES_PASSWORD=odoo \
    -e POSTGRES_DB=odoo \
    postgres:15

echo "Waiting for postgres..."
sleep 5

# Reset CI-generated files so oca_install_addons__deps_and_addons_path starts clean
truncate -s 0 "$REPO_DIR/test-requirements.txt"
rm -f "$REPO_DIR/test-constraints.txt"

docker run --rm \
    --platform linux/amd64 \
    --network "$NETWORK" \
    -v "$REPO_DIR":/workspace \
    -e ADDONS_DIR=/workspace \
    -e PGHOST="$PG_CONTAINER" \
    -e PGDATABASE=odoo \
    -e PGUSER=odoo \
    -e PGPASSWORD=odoo \
    -e OCA_ENABLE_CHECKLOG_ODOO=1 \
    -e INCLUDE="${1:-}" \
    "$OCA_IMAGE" \
    bash -c "cd /workspace && oca_install_addons && oca_init_test_database && oca_run_tests"
