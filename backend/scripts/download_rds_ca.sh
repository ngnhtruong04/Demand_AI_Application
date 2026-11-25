#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
certificate_dir="$project_dir/certs"
certificate_path="$certificate_dir/global-bundle.pem"

mkdir -p "$certificate_dir"
curl --fail --location --silent --show-error \
  --output "$certificate_path" \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
chmod 0644 "$certificate_path"

echo "Saved AWS RDS CA bundle to $certificate_path"

