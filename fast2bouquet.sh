#!/bin/sh
#
# Wrapper script to execute the FAST to Enigma2 bouquet generator.
#


# ==============================================================================
# =                            CONFIGURATION SECTION                           =
# ==============================================================================
# All variables are optional. Comment out to use internal script defaults.

# ------------------------------------------------------------------------------
#  PROVIDER SELECTION
# ------------------------------------------------------------------------------
# Select which service(s) to generate.
# Options: all, plutotv, rakutentv, stvp (or comma-separated list)
# Default: all
# PROVIDER='plutotv'

# ------------------------------------------------------------------------------
#  PLUTO TV
# ------------------------------------------------------------------------------
# Display name and file prefix.
# Default: PlutoTV
# PLUTOTV_PROVIDER_NAME='PlutoTV-de'

# Manual hex transponder ID (auto-generated if omitted).
# Default: None
# PLUTOTV_TID='029A'

# Pluto TV JSON API URL.
# Default: https://api.pluto.tv/v2/channels
# PLUTOTV_SOURCE='https://api.pluto.tv/v2/channels'

# Mapping type for EPG: 'id' (UUID) or 'slug' (human readable).
# Default: id
# PLUTOTV_ID_TYPE='slug'

# ------------------------------------------------------------------------------
#  RAKUTEN TV (Note: Strictly geo-blocked!)
# ------------------------------------------------------------------------------
# Regional subset. Your IP must match the selected region.
# Options: al, at, ba, be, bg, ch, cz, de, dk, ee, es, fi, fr, gr, hr, ie,
#          is, it, jp, lt, lu, me, mk, nl, no, pl, pt, ro, rs, se, sk, uk
# Default: de
# RAKUTENTV_REGION='uk'

# Display name and file prefix.
# Default: RakutenTV
# RAKUTENTV_PROVIDER_NAME='RakutenTV-uk'

# Manual hex transponder ID (auto-generated if omitted).
# Default: None
# RAKUTENTV_TID='024A'

# ------------------------------------------------------------------------------
#  SAMSUNG TV PLUS
# ------------------------------------------------------------------------------
# Regional subset.
# Options: all,at,ca,ch,de,es,fr,gb,in,it,kr,us
# Default: de
# STVP_REGION='all'

# Display name and file prefix.
# Default: SamsungTVPlus
# STVP_PROVIDER_NAME='SamsungTVPlus-de'

# Manual hex transponder ID (auto-generated if omitted).
# Default: None
# STVP_TID='029A'

# Samsung TV Plus JSON API URL.
# Default: https://i.mjh.nz/SamsungTVPlus/.channels.json
# STVP_SOURCE='https://i.mjh.nz/SamsungTVPlus/.channels.json'

# Include all channels, ignoring the internal blacklist.
# Default: false
# STVP_IGNORE_BLACKLIST='true'

# ------------------------------------------------------------------------------
#  PICON SETTINGS
# ------------------------------------------------------------------------------
# Download missing picons.
# Options: true, false, overwrite
# Default: false
# DOWNLOAD_PICONS='overwrite'

# Use colorful picons for provider.
# Options: all, false, plutotv, rakutentv (or comma-separated list)
# Default: plutotv
# PICON_COLORFUL='plutotv,rakutentv'

# Target size (WIDTHxHEIGHT).
# Options: 100x60, 220x132, 400x170, 400x240
# Default: 220x132
# PICON_SIZE='400x240'

# Keep original picon dimensions.
# Default: false
# PICON_NO_RESIZE='true'

# Enable post-processing.
# Options: all, false, plutotv, rakutentv, stvp (or comma-separated list)
# Default: stvp
# PICON_POST_PROCESSING='all'

# Custom path to picon directory (overrides auto-discovery).
# Default: auto
# PICON_FOLDER='/media/usb/picon'

# ------------------------------------------------------------------------------
#  GLOBAL OPTIONS
# ------------------------------------------------------------------------------
# Service type: 4097 (Standard) or 5002 (exteplayer3/ffmpeg).
# Default: 4097
# SERVICE_TYPE='5002'

# Sort bouquets in reverse alphabetical order (Z-A).
# Default: false
# REVERSE_BOUQUETS='true'

# Merge all categories into a single bouquet per provider.
# Default: false
# ONE_BOUQUET='true'

# Do not reload Enigma2 service list after creation.
# Default: false
# NOT_RELOAD='true'

# Disable parallel processing.
# Default: false
# NO_PARALLEL='true'

# Suppress info messages, only log errors.
# Default: false
# QUIET='true'

# ------------------------------------------------------------------------------
#  ADVANCED CONFIGURATION
# ------------------------------------------------------------------------------
# FLAGS='--flag1 ARG'       # Flag with argument
# FLAGS="$FLAGS --flag2"    # Bol flag



# ==============================================================================
# =                            MAIN SCRIPT LOGIC                               =
# ==============================================================================

# ------------------------------------------------------------------------------
#  SYSTEM & PATH DISCOVERY
# ------------------------------------------------------------------------------
PYTHON_BIN=$(command -v python3)
SCRIPT_PATH="/usr/script/fast2bouquet.py"


# ------------------------------------------------------------------------------
#  ERROR HANDLING
# ------------------------------------------------------------------------------
if [ -z "$PYTHON_BIN" ]; then
    printf "ERROR: 'python3' not found in PATH.\n" >&2
    exit 1
fi

if [ ! -f "$SCRIPT_PATH" ]; then
    printf "ERROR: Python script not found at: %s\n" "$SCRIPT_PATH" >&2
    exit 1
fi


# ------------------------------------------------------------------------------
#  COMMAND CONSTRUCTION
# ------------------------------------------------------------------------------
set -- "$PYTHON_BIN" "$SCRIPT_PATH"

# String arguments
[ -n "$PROVIDER" ]                  && set -- "$@" --provider "$PROVIDER"
[ -n "$PLUTOTV_PROVIDER_NAME" ]     && set -- "$@" --plutotv-provider-name "$PLUTOTV_PROVIDER_NAME"
[ -n "$PLUTOTV_TID" ]               && set -- "$@" --plutotv-tid "$PLUTOTV_TID"
[ -n "$PLUTOTV_SOURCE" ]            && set -- "$@" --plutotv-source "$PLUTOTV_SOURCE"
[ -n "$PLUTOTV_ID_TYPE" ]           && set -- "$@" --plutotv-id-type "$PLUTOTV_ID_TYPE"
[ -n "$RAKUTENTV_REGION" ]          && set -- "$@" --rakutentv-region "$RAKUTENTV_REGION"
[ -n "$RAKUTENTV_PROVIDER_NAME" ]   && set -- "$@" --rakutentv-provider-name "$RAKUTENTV_PROVIDER_NAME"
[ -n "$RAKUTENTV_TID" ]             && set -- "$@" --rakutentv-tid  "$RAKUTENTV_TID"
[ -n "$RAKUTENTV_SOURCE" ]          && set -- "$@" --rakutentv-source "$RAKUTENTV_SOURCE"
[ -n "$STVP_REGION" ]               && set -- "$@" --stvp-region "$STVP_REGION"
[ -n "$STVP_PROVIDER_NAME" ]        && set -- "$@" --stvp-provider-name "$STVP_PROVIDER_NAME"
[ -n "$STVP_TID" ]                  && set -- "$@" --stvp-tid "$STVP_TID"
[ -n "$STVP_SOURCE" ]               && set -- "$@" --stvp-source "$STVP_SOURCE"
[ -n "$PICON_COLORFUL" ]            && set -- "$@" --picon-colorful "$PICON_COLORFUL"
[ -n "$PICON_SIZE" ]                && set -- "$@" --picon-size "$PICON_SIZE"
[ -n "$PICON_POST_PROCESSING" ]     && set -- "$@" --picon-post-processing "$PICON_POST_PROCESSING"
[ -n "$PICON_FOLDER" ]              && set -- "$@" --picon-folder "$PICON_FOLDER"
[ -n "$SERVICE_TYPE" ]              && set -- "$@" --service-type "$SERVICE_TYPE"

# Boolean Flags (Translate 'true' variables to python flags)
[ "$NO_PARALLEL" = "true" ]             && set -- "$@" --no-parallel
[ "$NOT_RELOAD" = "true" ]              && set -- "$@" --not-reload
[ "$ONE_BOUQUET" = "true" ]             && set -- "$@" --one-bouquet
[ "$PICON_NO_RESIZE" = "true" ]         && set -- "$@" --picon-no-resize
[ "$QUIET" = "true" ]                   && set -- "$@" --quiet
[ "$REVERSE_BOUQUETS" = "true" ]        && set -- "$@" --reverse-bouquets
[ "$STVP_IGNORE_BLACKLIST" = "true" ]   && set -- "$@" --stvp-ignore-blacklist

# Special handling for Picons (Download vs Overwrite)
if [ "$DOWNLOAD_PICONS" = "overwrite" ]; then
    set -- "$@" --download-overwrite-picons
elif [ "$DOWNLOAD_PICONS" = "true" ]; then
    set -- "$@" --download-picons
fi

# Advanced Flags (shellcheck disable SC2086 because we want splitting)
if [ -n "$FLAGS" ]; then
    # shellcheck disable=SC2086
    set -- "$@" $FLAGS
fi


# ------------------------------------------------------------------------------
#  EXECUTION
# ------------------------------------------------------------------------------
printf "Starting Pluto TV Update...\n"

"$@"
RESULT=$?

if [ $RESULT -eq 0 ]; then
    printf "Update finished successfully.\n"
else
    printf "Update failed with exit code %s.\n" "$RESULT" >&2
    exit $RESULT
fi
