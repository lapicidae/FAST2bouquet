#!/bin/sh
#
# Wrapper script to execute the PlutoTV to Enigma2 bouquet generator.
#


# --- Configuration Section ---
# All variables are optional. Comment out to use internal script defaults.

# Provider name used for file prefixes and bouquet names [default: PlutoTV]
# PROVIDER="PlutoTV"

# Mapping type for EPG: 'slug' (human readable) or 'id' (UUID) [default: slug]
ID_TYPE="id"

# Enigma2 service type: e.g. 4097 (Standard) or 5002 (exteplayer3/ffmpeg) [default: 4097]
# SERVICE_TYPE='5002'

# Color variant for Picons: 'color' or 'solid' [default: color]
# PICON_COLOR='solid'

# Custom path to the picon directory (overrides default Enigma2 search order) [default: auto]
# PICON_FOLDER='/media/usb/picon'

# Sort bouquets in reverse alphabetical order (Z-A) [default: false]
# REVERSE_BOUQUETS='true'

# Merge all categories into a single bouquet with markers [default: false]
# ONE_BOUQUET='true'

# Download missing picons (true/false/overwrite) [default: false]
# DOWNLOAD_PICONS='overwrite'

# Do not reload the Enigma2 service list after creating the bouquet [default: false]
# NOT_RELOAD='true'

# Suppress info messages, only log errors [default: false]
# QUIET='true'


# --- Advanced configuration ---
# FLAGS='--source SOURCE'       # Alternative Pluto TV JSON API URL [default: https://api.pluto.tv/v2/channels]
# FLAGS="$FLAGS --tid TID"      # Manual hex transponder ID (auto-generated from provider name if omitted) [default: None]


# --- System & Path Discovery ---

PYTHON_BIN=$(command -v python3)
SCRIPT_PATH="/usr/script/pluto2bouquet.py"


# --- Error Handling ---

if [ -z "$PYTHON_BIN" ]; then
    printf "ERROR: 'python3' not found in PATH.\n" >&2
    exit 1
fi

if [ ! -f "$SCRIPT_PATH" ]; then
    printf "ERROR: Python script not found at: %s\n" "$SCRIPT_PATH" >&2
    exit 1
fi


# --- Command Construction ---

set -- "$PYTHON_BIN" "$SCRIPT_PATH"

# String arguments
[ -n "$PROVIDER" ]     && set -- "$@" --provider "$PROVIDER"
[ -n "$ID_TYPE" ]      && set -- "$@" --id-type "$ID_TYPE"
[ -n "$SERVICE_TYPE" ] && set -- "$@" --service-type "$SERVICE_TYPE"
[ -n "$PICON_COLOR" ]  && set -- "$@" --picon-color "$PICON_COLOR"
[ -n "$PICON_FOLDER" ]    && set -- "$@" --picon-folder "$PICON_FOLDER"

# Boolean Flags (Translate 'true' variables to python flags)
[ "$REVERSE_BOUQUETS" = "true" ] && set -- "$@" --reverse-bouquets
[ "$ONE_BOUQUET" = "true" ]      && set -- "$@" --one-bouquet
[ "$NOT_RELOAD" = "true" ]       && set -- "$@" --not-reload
[ "$QUIET" = "true" ]            && set -- "$@" --quiet

# Special handling for Picons (Download vs Overwrite)
if [ "$DOWNLOAD_PICONS" = "overwrite" ]; then
    set -- "$@" --download-overwrite-picons
elif [ "$DOWNLOAD_PICONS" = "true" ]; then
    set -- "$@" --download-picons
fi

# Advanced Flags (shellcheck disable SC2086 because we want splitting for SOURCE/TID)
if [ -n "$FLAGS" ]; then
    # shellcheck disable=SC2086
    set -- "$@" $FLAGS
fi


# --- Execution ---

printf "Starting Pluto TV Update...\n"

"$@"
RESULT=$?

if [ $RESULT -eq 0 ]; then
    printf "Update finished successfully.\n"
else
    printf "Update failed with exit code %s.\n" "$RESULT" >&2
    exit $RESULT
fi
