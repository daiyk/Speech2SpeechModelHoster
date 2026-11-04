#!/bin/bash
cd "$(dirname "$0")" || exit 1
./scripts/serve.sh
status=$?
if [[ $status -ne 0 && $status -ne 130 ]]; then
  read -r -p "Server stopped with an error. Press Return to close. " _
fi
exit "$status"
