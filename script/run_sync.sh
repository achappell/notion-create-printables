#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE"
  exit 2
fi

# Load .env literally (without shell eval) so cookie values containing '$' work.
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -z "$line" ]] && continue
  [[ "$line" == \#* ]] && continue
  [[ "$line" != *=* ]] && continue

  key="${line%%=*}"
  value="${line#*=}"

  # Trim surrounding quotes if present.
  if [[ "${value:0:1}" == '"' && "${value: -1}" == '"' ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
    value="${value:1:${#value}-2}"
  fi

  export "$key=$value"
done < "$ENV_FILE"

/usr/bin/env python3 "$SCRIPT_DIR/makerworld_to_notion.py" "$@"
