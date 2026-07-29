#!/bin/sh
# __PURPOSE__
#
# Composition idiom: run a sibling tool as "$(dirname "$0")/<dep>" and
# declare "<dep>" in this tool's `requires` list in tmt.json.
set -eu

usage() {
    printf '%s\n' 'usage: __USAGE__'
    printf '%s\n' '__PURPOSE__'
}

json=0
while [ $# -gt 0 ]; do
    case $1 in
        --help)
            usage
            exit 0
            ;;
        --json)
            json=1
            ;;
        *)
            printf '%s\n' "__TOOL_ID__: unknown argument: $1" >&2
            exit 2
            ;;
    esac
    shift
done

# Replace with the derived logic. In --json mode emit exactly one compact
# key-sorted JSON object with "v":1 on stdout (cli-v1).
if [ "$json" -eq 1 ]; then
    printf '%s\n' '{"result":null,"v":1}'
else
    printf 'result\tnull\n'
fi
