#!/usr/bin/env bash
set -euo pipefail

source="$(cd "${1:?Usage: bash scripts/check-account-free.sh <source>}" && pwd)"
scripts="$(cd "$(dirname "$0")" && pwd)"

test -f "$source/kernel/model/unlock_cloud_account_test.go"
test -f "$source/kernel/api/unlock_cloud_account_test.go"
node "$scripts/check-account-ui.mjs" "$source"
cd "$source/kernel"
go test -tags "fts5 sqlcipher" ./model ./api \
  -run '^(TestUnlock|TestCloudAccount|TestCloudRepoAuthFailure|TestCloudUserRefresh|TestAPIContractSettingErrorsAndAdmission)' \
  -count=1
