#!/usr/bin/env sh
script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd) || exit 1
exec python3 "$script_dir/run.py" "$@"
