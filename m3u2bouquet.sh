#!/bin/bash

if [ -z "$1" ]; then
	if [ -z "$1" ]; then
    	printf 'ERROR: No m3u file / url set!\n\n'
	fi
    printf "Usage: %s m3ufile Name TID ServiceType\n" "$0"
    printf "m3ufile: Name of the m3u file indluding path\n"
    printf "Provider: Provider Name, to identfy the entries in the bouquet and channels file\n"
    printf "TID: Up to 4 digit hexadecimal number, to disguish the services from different providers\n"
    printf "Servicetype: 1, 4097, 5001 or 5002.  If omitted 4097 is used\n"
    printf "Version 1.2-pluto\n"
    exit 1
fi

m3ufile="$1"

Provider="${2:-PlutoTV}"

# TID
TID="$3"
if [ -z "$TID" ]; then 
    TID=$(printf '%s' "$Provider" | md5sum | cut -c1-4)
fi

Lead=${4:-4097}

IDfromURL='true'
confDir='/etc/epgimport'
bouquetDir='/etc/enigma2'
piconDIR='/usr/share/enigma2/picon'
Channelsfile="${Provider}.channels.xml"
EPGsource="${Provider}.sources.xml"
xmltvURL='https://i.mjh.nz/PlutoTV/all.xml.gz'
xmltvURLmirror='https://github.com/matthuisman/i.mjh.nz/raw/refs/heads/master/PlutoTV/all.xml.gz'

if [ -w '/dev/shm' ]; then
    TMPDIR="/dev/shm"
else
    TMPDIR="${TMPDIR:-/tmp}"
fi
TMPDIR=$(mktemp -d -p "$TMPDIR" --suffix="-m3u2bouquet")

trap 'rm -rf "$TMPDIR"' EXIT

if [ ! -w "$confDir" ]; then
    confDir="${PWD}"
fi

if [ ! -w "$bouquetDir" ]; then
    bouquetDir="${PWD}"
fi

if [ ! -w "$piconDIR" ]; then
    piconDIR="${PWD}/picon"
fi

for f in "${bouquetDir}/userbouquet.IP_${Provider}"*.*; do
    [ -e "$f" ] || continue
    rm "$f"
done

# clean the bouquets.tv file
Clean="userbouquet.IP_${Provider}"
if [ -e "${bouquetDir}/bouquets.tv" ]; then
    grep -v "$Clean" "${bouquetDir}/bouquets.tv" > "${bouquetDir}/bouquets.new"
    mv -f "${bouquetDir}/bouquets.new" "${bouquetDir}/bouquets.tv"
fi

# clean the custom.channels.xml file
if [ -e "${confDir}/${Channelsfile}" ]; then
    grep -v "IP_${Provider}\|channels\|encoding" "${confDir}/${Channelsfile}" > "${TMPDIR}/${Channelsfile}"
fi

# Ask if logos should be downloaded
printf "Would you like to download the channel logos (picons), if available in %s? [y/N]: " "$m3ufile"
read -r download_logos

if [[ "${download_logos,,}" == "y" ]]; then
    mkdir -p "$piconDIR"
    printf "Logos will be prepared in: %s\n" "$piconDIR"
fi

j=0
while read -r line; do
    if [[ "$line" == "#EXTM3"* ]]; then
        read -r line
    fi

	# Reset metadata variables
    SID="" ChannelName="" ChannelID="" LogoURL="" group_title="" group_title1=""

    j=$((j+1))

    # Standardize tag
    line=${line/tvg-ID=/tvg-id=}

    # Extract SID
    if [[ "$line" == *"tvg-chno"* ]]; then
            SID=${line##*tvg-chno=\"}
            SID=${SID%%\"*}
        else
            SID=$j
    fi
    printf -v HexSID "%x" "$SID"

    # ChannelName (Extracted early to use as fallback)
    if [[ "$line" == *"tvg-name"* ]]; then
            ChannelName=${line##*tvg-name=\"}
            ChannelName=${ChannelName%%\"*}
        else
            ChannelName=${line#*,}
            ChannelName=${ChannelName//$'\r'}
    fi
    if [ "$ChannelName" = "" ]; then
            ChannelName=${line#*,}
            ChannelName=${ChannelName//$'\r'}
    fi

    if [[ "$line" == *"tvg-logo"* ]]; then
        LogoURL=${line##*tvg-logo=\"}
        LogoURL=${LogoURL%%\"*}
    fi

    # Read URL line immediately to have it available for ID extraction
    read -r url
    # Clean URL for bouquet use
    url_clean=${url//:/%3a}
    url_clean=${url_clean//$'\r'}

    # ChannelID Logic with Fallback
    if [[ ${IDfromURL,,} != 'true' ]]; then
        if [[ "$line" == *"tvg-id"* ]]; then   
                ChannelID=${line##*tvg-id=\"}
                ChannelID=${ChannelID%%\"*}
        fi
        
        # Fallback if tvg-id is missing or empty ("")
        if [ -z "$ChannelID" ]; then
            # Use ChannelName as fallback ID (remove spaces)
            ChannelID="${ChannelName// /}"
        fi
    else
        # Extract ID from Pluto URL
        tmp_id=${url##*/channel/}
        ChannelID=${tmp_id%%/*}
    fi

    # Group / Category logic
    if [[ "$line" == *"group-title"* ]]; then
            Group=${line##*group-title=\"}
            group_title=${Group%%\"*}
        elif [[ "$Group" == *"group-title"* ]]; then
            group_title1=${Group##*group-title=\"}
            group_title1=${group_title1%%\"*}
    fi

    # Create Picon filename in Enigma2 format
    PiconName="${Lead}_0_1_${HexSID}_${TID}_0_0_0_0"
    PiconName="${PiconName^^}"

    # Prepare logo download list
    if [[ "${download_logos,,}" == "y" && -n "$LogoURL" ]]; then
        if [[ "$LogoURL" == http* ]]; then
            ext="${LogoURL##*.}"
            [[ "$ext" != "png" && "$ext" != "jpg" ]] && ext="png"
            printf "%s %s.%s\n" "$LogoURL" "$PiconName" "$ext" >> "${TMPDIR}/picon_list.txt"
        fi
    fi

    Category="$group_title"" ""$group_title1"
    Category=${Category// | /-}    
    Cat1=${Category// /_}
    Cat1=${Cat1//+/}    
    Cat="${Provider}_${Cat1}"

    # Create bouquet file
    if [[ ! -f "${bouquetDir}/userbouquet.IP_${Cat}.tv" ]]
    then
         printf "#NAME %s %s\n" "$Provider" "$Category" > "${bouquetDir}/userbouquet.IP_${Cat}.tv"
         printf '#SERVICE 1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "userbouquet.IP_%s.tv" ORDER BY bouquet\n' "$Cat" >> "${bouquetDir}/bouquets.tv"
    fi

    # Write to custom.channels.xml
    if [ -n "$ChannelID" ] 
    then
        ChannelID=${ChannelID//&/and}
        printf '\t<channel id="%s">%s:0:1:%s:%s:0:0:0:0:3:http%%3a//example.com</channel> <!-- %s -->\n' "$ChannelID" "$Lead" "$HexSID" "$TID" "$ChannelName" >> "${TMPDIR}/${Channelsfile}"
    fi

    # Write to userbouquet
	{
		printf "#SERVICE %s:0:1:%s:%s:0:0:0:0:3:%s:%s\n" "$Lead" "$HexSID" "$TID" "$url_clean" "$ChannelName"
		printf "#DESCRIPTION %s\n" "$ChannelName"
	} >> "${bouquetDir}/userbouquet.IP_${Cat}.tv"

done < "$m3ufile"

# Execute logo downloads if requested
if [[ "${download_logos,,}" == "y" && -f "${TMPDIR}/picon_list.txt" ]]; then
    printf "Downloading logos, please wait...\n"
    overwrite_all="n"
    while read -r dl_url dl_filename; do
        if [ -f "$piconDIR/$dl_filename" ] && [ "$overwrite_all" != "y" ]; then
            printf "File '%s' already exists. Overwrite? [y]es / [n]o / [a]ll: " "$dl_filename"
            read -r ans </dev/tty
            case "${ans,,}" in
                a) overwrite_all="y" ;;
                y) ;;           
                *) continue ;;  
            esac
        fi
        wget -qO "$piconDIR/$dl_filename" "$dl_url"
    done < "${TMPDIR}/picon_list.txt"
fi

# reconstruct the custom.channels.xml file
if [ -e "${confDir}/${Channelsfile}" ]; then
    rm "${confDir}/${Channelsfile}"
fi
printf '<?xml version="1.0" encoding="utf-8"?>\n<channels>\n' > "${TMPDIR}/Header.xml"
cat "${TMPDIR}/Header.xml" "${TMPDIR}/${Channelsfile}" > "${confDir}/${Channelsfile}"
printf '</channels>\n' >> "${confDir}/${Channelsfile}"
rm "${TMPDIR}/Header.xml"
wget -qO - "http://127.0.0.1/web/servicelistreload?mode=0"

EPGsource_full="${confDir}/${EPGsource}"
{
    printf '<?xml version="1.0" encoding="utf-8"?>\n'
    printf '<sources>\n'
    printf '\t<sourcecat sourcecatname="Pluto TV (%s)">\n' "$(cut -d/ -f1 <<< "${xmltvURL#*//}")"
    printf '\t\t<source type="gen_xmltv" nocheck="1" channels="%s">\n' "$Channelsfile"
    printf '\t\t\t<description>Pluto TV (%s)</description>\n' "${xmltvURL##*/}"
    printf '\t\t\t<url>%s</url>\n' "$xmltvURL"
	if [ -n "$xmltvURLmirror" ]; then
		printf '\t\t\t<url>%s</url>\n' "$xmltvURLmirror"
	fi
    printf '\t\t</source>\n'
    printf '\t</sourcecat>\n'
    printf '</sources>\n'
} > "$EPGsource_full"
