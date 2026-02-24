#!/bin/sh
#
# Wrapper script to execute the FAST to Enigma2 bouquet generator.
#


# --- Configuration Section ---
# All variables are optional. Comment out to use internal script defaults.

## Provider selection ##
# Select which service(s) to generate (all,plutotv,rakuten,stvp) [default: all]
# PROVIDER='plutotv'

## Pluto TV ##
# Display name and file prefix for Pluto TV [default: PlutoTV]
# PLUTOTV_PROVIDER_NAME='PlutoTV-de'

# Manual hex transponder ID (auto-generated from provider name if omitted) [default: None]
# PLUTOTV_TID='029A'

# Pluto TV JSON API URL [default: https://api.pluto.tv/v2/channels]
# PLUTOTV_SOURCE='https://api.pluto.tv/v2/channels'

# Mapping type for EPG: 'id' (UUID) or 'slug' (human readable) [default: id]
# PLUTOTV_ID_TYPE='slug'

## Rakuten TV ##
# Regional subset for Rakuten TV. Note: Rakuten TV is strictly geo-blocked; your IP must match the selected region. (al,at,ba,be,bg,ch,cz,de,dk,ee,es,fi,fr,gr,hr,ie,is,it,jp,lt,lu,me,mk,nl,no,pl,pt,ro,rs,se,sk,uk) [default: de]
# RAKUTENTV_REGION='uk'

# Display name and file prefix for Rakuten TV [default: RakutenTV]
# RAKUTENTV_PROVIDER_NAME='RakutenTV-de'

# Manual hex transponder ID (auto-generated from provider name if omitted) [default: None]
# RAKUTENTV_TID='024A'

## Samsung TV Plus ##
# Regional subset for Samsung TV Plus (all,at,ca,ch,de,es,fr,gb,in,it,kr,us) [default: de]
# STVP_REGION='all'

# Display name and file prefix for Samsung TV Plus [default: SamsungTVPlus]
# STVP_PROVIDER_NAME='SamsungTVPlus-de'

# Manual hex transponder ID (auto-generated from provider name if omitted) [default: None]
# STVP_TID='029A'

# Samsung TV Plus JSON API URL [default: https://i.mjh.nz/SamsungTVPlus/.channels.json]
# STVP_SOURCE='https://i.mjh.nz/SamsungTVPlus/.channels.json'

# Include all channels, ignoring the internal STVP blacklist [default: False]
# STVP_IGNORE_BLACKLIST='true'

## Picon ##
# Download missing picons (true/false/overwrite) [default: false]
# DOWNLOAD_PICONS='overwrite'

# Use colorful picons for provider (all, false, plutotv, rakutentv or a comma-separated list like 'plutotv,rakutentv') [default: plutotv]
# PICON_COLORFUL='solid'

# Enable picon post-processing (all, false, plutotv, rakutentv, stvp or a comma-separated list like 'plutotv,stvp') [default: rakutentv,stvp]
# PICON_POST_PROCESSING='all'

# Custom path to the picon directory (overrides default Enigma2 search order) [default: auto]
# PICON_FOLDER='/media/usb/picon'

## Global ##
# Enigma2 service type: e.g. 4097 (Standard) or 5002 (exteplayer3/ffmpeg) [default: 4097]
# SERVICE_TYPE='5002'

# Sort bouquets in reverse alphabetical order (Z-A) [default: false]
# REVERSE_BOUQUETS='true'

# Merge all categories with markers into a single bouquet per provider [default: false]
# ONE_BOUQUET='true'

# Do not reload the Enigma2 service list after creating the bouquet [default: false]
# NOT_RELOAD='true'

# Disable parallel processing [default: false]
# NO_PARALLEL='true'

# Suppress info messages, only log errors [default: false]
# QUIET='true'


# --- Advanced configuration ---
# FLAGS='--flag1 ARG'       # Flag with argument
# FLAGS="$FLAGS --flag2"    # Bol flag


# --- System & Path Discovery ---

PYTHON_BIN=$(command -v python3)
SCRIPT_PATH="/usr/script/fast2bouquet.py"


# --- Error Handling ---

if [ -z "$PYTHON_BIN" ]; then
    printf "ERROR: 'python3' not found in PATH.\n" >&2
    exit 1
fi

if [ ! -f "$SCRIPT_PATH" ]; then
    printf "ERROR: Python script not found at: %s\n" "$SCRIPT_PATH" >&2
    exit 1
fi


## --- Command Construction ---

set -- "$PYTHON_BIN" "$SCRIPT_PATH"

# String arguments
[ -n "$PROVIDER" ]              	&& set -- "$@" --provider "$PROVIDER"
[ -n "$PLUTOTV_PROVIDER_NAME" ] 	&& set -- "$@" --plutotv-provider-name "$PLUTOTV_PROVIDER_NAME"
[ -n "$PLUTOTV_TID" ]           	&& set -- "$@" --plutotv-tid "$PLUTOTV_TID"
[ -n "$PLUTOTV_SOURCE" ]        	&& set -- "$@" --plutotv-source "$PLUTOTV_SOURCE"
[ -n "$PLUTOTV_ID_TYPE" ]      		&& set -- "$@" --plutotv-id-type "$PLUTOTV_ID_TYPE"
[ -n "$RAKUTENTV_REGION" ]        	&& set -- "$@" --rakutentv-region "$RAKUTENTV_REGION"
[ -n "$RAKUTENTV_PROVIDER_NAME" ] 	&& set -- "$@" --rakutentv-provider-name "$RAKUTENTV_PROVIDER_NAME"
[ -n "$RAKUTENTV_TID" ]           	&& set -- "$@" --rakutentv-tid  "$RAKUTENTV_TID"
[ -n "$RAKUTENTV_SOURCE" ]			&& set -- "$@" --rakutentv-source "$RAKUTENTV_SOURCE"
[ -n "$STVP_REGION" ]           	&& set -- "$@" --stvp-region "$STVP_REGION"
[ -n "$STVP_PROVIDER_NAME" ]    	&& set -- "$@" --stvp-provider-name "$STVP_PROVIDER_NAME"
[ -n "$STVP_TID" ]              	&& set -- "$@" --stvp-tid "$STVP_TID"
[ -n "$STVP_SOURCE" ]           	&& set -- "$@" --stvp-source "$STVP_SOURCE"
[ -n "$PICON_COLORFUL" ]           	&& set -- "$@" --picon-colorful "$PICON_COLORFUL"
[ -n "$PICON_POST_PROCESSING" ] 	&& set -- "$@" --picon-post-processing "$PICON_POST_PROCESSING"
[ -n "$PICON_FOLDER" ]          	&& set -- "$@" --picon-folder "$PICON_FOLDER"
[ -n "$SERVICE_TYPE" ]          	&& set -- "$@" --service-type "$SERVICE_TYPE"

# Boolean Flags (Translate 'true' variables to python flags)
[ "$REVERSE_BOUQUETS" = "true" ]        && set -- "$@" --reverse-bouquets
[ "$ONE_BOUQUET" = "true" ]             && set -- "$@" --one-bouquet
[ "$NOT_RELOAD" = "true" ]              && set -- "$@" --not-reload
[ "$NO_PARALLEL" = "true" ]             && set -- "$@" --no-parallel
[ "$QUIET" = "true" ]                   && set -- "$@" --quiet
[ "$STVP_IGNORE_BLACKLIST" = "true" ]   && set -- "$@" --stvp-ignore-blacklist

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
