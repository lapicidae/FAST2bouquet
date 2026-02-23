#!/usr/bin/env python3
import os
import re
import glob
import hashlib
import argparse
import urllib.request
import json
import uuid
import logging
from collections import defaultdict
from PIL import Image, ImageDraw
from urllib.error import URLError

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


# --- Internal Configuration ---

# Pluto TV Specifics
PLUTOTV_EPG_LANGS = ['all', 'ar', 'br', 'ca', 'cl', 'de', 'dk', 'es', 'fr', 'gb', 'it', 'mx', 'no', 'se', 'us']

# Samsung TV Plus Specifics
STVP_REGIONS = ['all', 'at', 'ca', 'ch', 'de', 'es', 'fr', 'gb', 'in', 'it', 'kr', 'us']
STVP_BLACKLIST = [
    "DE1000002V4",      # SMTOWN
    "DE3000016Q",       # Sony One Comedy TV
    "DE300002CL",       # Sony One Comedy HITS
    "DE300003AV",       # Sony One Thriller TV
    "DE30000489",       # Sony One Action HITS
    "DE300005NB",       # Sony One Best Of
    "DEBC3000002Z5",    # Comedy Mix
    "DEBC470000128",    # DAZN FAST+
    "DEBC4700002Z2",    # Entertainment Mix
    "DEBD700001C5",     # DAZN Rise
]


def parse_args():
    """
    Parse command-line arguments for the Pluto TV script.

    Returns
    -------
    argparse.Namespace
        An object containing all parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description="Generate Enigma2 bouquets and M3U from Pluto TV JSON API.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # Provider group
    prov_group = parser.add_argument_group("Provider selection")
    prov_group.add_argument("--provider", choices=["all", "plutotv", "stvp"], default="all", help="Select which service(s) to generate")

    # PlutoTV group
    plutotv_group = parser.add_argument_group("Pluto TV")
    plutotv_group.add_argument("--plutotv-provider-name", default="PlutoTV", help="Display name and file prefix for Pluto TV")
    plutotv_group.add_argument("--plutotv-tid", help="Manual hex transponder ID (auto-generated from provider name if omitted)")
    plutotv_group.add_argument("--plutotv-source", default="https://api.pluto.tv/v2/channels", help="Pluto TV JSON API URL")
    plutotv_group.add_argument("--plutotv-id-type", choices=["id", "slug"], default="id", help="Mapping type for EPG: 'id' (UUID) or 'slug' (human readable)")

    # Samsung TV Plus group
    stvp_group = parser.add_argument_group("Samsung TV Plus")
    stvp_group.add_argument("--stvp-region", choices=STVP_REGIONS, default="all", help="Regional subset for Samsung TV Plus")
    stvp_group.add_argument("--stvp-provider-name", default="SamsungTVPlus", help="Display name and file prefix for Samsung TV Plus")
    stvp_group.add_argument("--stvp-tid", help="Manual hex transponder ID (auto-generated from provider name if omitted)")
    stvp_group.add_argument("--stvp-source", default="https://i.mjh.nz/SamsungTVPlus/.channels.json", help="Samsung TV Plus JSON API URL")
    stvp_group.add_argument("--stvp-ignore-blacklist", action="store_true", help="Include all channels, ignoring the internal STVP blacklist")

    # Output selection group
    output_group = parser.add_argument_group("Output options")
    output_group.add_argument("-p", "--playlist", help="Create an M3U playlist file and save it in the specified path")
    output_group.add_argument("-P", "--playlist-only", help="Create ONLY an M3U playlist file and save it in the specified path")
    output_group.add_argument("-o", "--one-bouquet", action="store_true", help="Merge all categories with markers into a single bouquet per provider")
    output_group.add_argument("-r", "--reverse-bouquets", action="store_true", help="Sort bouquets in reverse alphabetical order (Z-A)")

    # Picon group
    picon_group = parser.add_argument_group("Picon settings")
    picon_group.add_argument("-d", "--download-picons", action="store_true", help="Download missing picons")
    picon_group.add_argument("-D", "--download-overwrite-picons", action="store_true", help="Download and overwrite existing picons")
    picon_group.add_argument("-c", "--picon-color", choices=["color", "solid"], default="color", help="Choose between color or solid white logos (if available)")
    picon_group.add_argument("--picon-post-processing", choices=["all", "false", "plutotv", "stvp"], default="stvp", help="Apply slightly rounded corners to picons from the selected provider")
    picon_group.add_argument("-f", "--picon-folder", help="Custom path to the picon directory (overrides default search order)")

    # Technical group
    tec_group = parser.add_argument_group("Technical configuration")
    tec_group.add_argument("-n", "--not-reload", action="store_true", help="Do not reload the Enigma2 service list after creating the bouquet")
    tec_group.add_argument("-s", "--service-type", default="4097", help="Enigma2 service type: 4097 (GstPlayer). 5001, 5002 and 5003 are used by the ServiceApp plugin and additional players such as ffmpeg + exteplayer3")

	# Advanced group
    # config_group = parser.add_argument_group("Advanced configuration")

    # Global switches
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress info messages, only log errors")

    return parser.parse_args()

def normalize_name(name):
    """
    Normalize a string for use in filenames or IDs using regex.

    Parameters
    ----------
    name : str
        The raw string to be normalized.

    Returns
    -------
    str
        The cleaned string with non-word characters replaced by dashes.
    """
    name = re.sub(r"[^\w]+", "-", name)
    return name.strip("-")

def get_system_paths(custom_picon_folder=None):
    """
    Determine system paths for EPG import, Enigma2, and picons.

    Parameters
    ----------
    custom_picon_folder : str, optional
        A user-defined path for picons that overrides the default search order.

    Returns
    -------
    tuple of str
        A tuple containing (config_path, bouquet_path, picon_path).
    """
    pwd = os.getcwd()
    def check_path(path, fallback):
        return path if os.access(path, os.W_OK) else fallback
    
    # Determine the best picon path
    picon_path = None
    if custom_picon_folder and os.access(custom_picon_folder, os.W_OK):
        picon_path = custom_picon_folder
    else:
        # Standard Enigma2 picon search order
        search_paths = [
            '/media/cf/picon',
            '/media/mmc/picon',
            '/media/usb/picon',
            '/picon',
            '/media/hdd/picon',
            '/usr/share/enigma2/picon'
        ]
        for path in search_paths:
            if os.path.isdir(path) and os.access(path, os.W_OK):
                picon_path = path
                break
        
        # Fallback to local directory if no valid path was found
        if not picon_path:
            picon_path = os.path.join(pwd, 'picon')

    return (check_path('/etc/epgimport', pwd), 
            check_path('/etc/enigma2', pwd), 
            picon_path)

def clean_old_files(bouquet_dir, conf_dir, prefix, channels_file):
    """
    Remove old bouquet files and clean up references in bouquets.tv.

    Parameters
    ----------
    bouquet_dir : str
        Path to the Enigma2 bouquet directory.
    conf_dir : str
        Path to the EPG import configuration directory.
    prefix : str
        The prefix string used for identifying relevant bouquet files.
    channels_file : str
        Filename of the channels XML file to be deleted.
    """
    # Remove bouquet files matching the provider prefix
    for pattern in [f"{prefix}_*.tv", f"{prefix}.tv"]:
        for f in glob.glob(os.path.join(bouquet_dir, pattern)):
            try:
                os.remove(f)
            except OSError:
                pass

    # Filter out provider-specific bouquet references from bouquets.tv
    bouquets_tv = os.path.join(bouquet_dir, "bouquets.tv")
    if os.path.exists(bouquets_tv):
        with open(bouquets_tv, 'r') as f:
            lines = [L for L in f if f'FROM BOUQUET "{prefix}' not in L]
        with open(bouquets_tv, 'w') as f:
            f.writelines(lines)

    # Remove existing EPG channels configuration
    c_path = os.path.join(conf_dir, channels_file)
    if os.path.exists(c_path):
        os.remove(c_path)

def fetch_plutotv_data(api_url, id_type, picon_color):
    """
    Fetch and parse channel data from the Pluto TV JSON API.

    Parameters
    ----------
    api_url : str
        The URL of the Pluto TV API.
    id_type : str
        The type of ID to use for tvg-id mapping ('slug' or 'id').
    picon_color : str
        The style of logo to fetch ('color' or 'solid').

    Returns
    -------
    list of dict
        A list containing dictionaries with channel metadata and stream URLs.
    """
    try:
        req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        logging.error(f"Error fetching data: {e}")
        return []

    channels = []
    # Generate unique session identifiers for the stream URLs
    dev_id, session_id = str(uuid.uuid4()), str(uuid.uuid4())
    url_mask = (
        "https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv/stitch/hls/channel/{_id}/master.m3u8?"
        "appName=web&appVersion=9.19.0&deviceDNT=0&deviceId={dev_id}&deviceMake=firefox"
        "&deviceModel=web&deviceType=web&deviceVersion=147.0.0&serverSideAds=false&sid={sid}"
    )
    for item in data:
        _id = item.get("_id")
        if not _id:
            continue
            
        # Clean metadata and ensure fallback for channel identification
        name = item.get("name", "Unknown").strip()
        category = (item.get("category") or "Uncategorized").strip()
        channel_id = (item.get("slug") if id_type == "slug" else _id) or _id

        # Get paths and treat "missing.png" as an empty string to trigger fallback logic
        color_path = item.get("colorLogoPNG", {}).get("path", "")
        if "missing.png" in color_path:
            color_path = ""
        
        solid_path = item.get("solidLogoPNG", {}).get("path", "")
        if "missing.png" in solid_path:
            solid_path = ""
        
        # Global fallback URL from Wikimedia
        wikimedia_fallback = 'https://upload.wikimedia.org/wikipedia/commons/thumb/c/c3/Pluto_TV_logo_2024.svg/220px-Pluto_TV_logo_2024.svg.png'

        # Fallback logic: Choice -> Alternative -> Wikimedia
        if picon_color == "solid":
            logo_url = solid_path or color_path or wikimedia_fallback
        else:
            logo_url = color_path or solid_path or wikimedia_fallback

        channels.append({
            "sid": item.get("number", 0),
            "name": name,
            "category": category,
            "channel_id": channel_id,
            "logo_url": logo_url,
            "url": url_mask.format(_id=_id, dev_id=dev_id, sid=session_id)
        })
    return channels

def fetch_stvp_data(api_url, region, ignore_blacklist=False):
    """
    Fetch and parse channel data from the Samsung TV Plus JSON API.

    Parameters
    ----------
    api_url : str
        The URL to the Samsung TV Plus JSON API.
    region : str
        The region code to filter channels.
    ignore_blacklist : bool, optional
        If True, the internal STVP_BLACKLIST will be ignored. Default is False.

    Returns
    -------
    list of dict
        A list containing dictionaries with channel metadata and stream URLs.
    """
    try:
        # User-agent as requested for Samsung API
        req = urllib.request.Request(api_url, headers={'User-Agent': 'okhttp/4.12.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        logging.error(f"Error fetching Samsung TV Plus data from {api_url}: {e}")
        return []

    channels = []
    regions_to_scan = [region] if region != "all" else [r for r in data["regions"] if r != "all"]
    
    for reg_key in regions_to_scan:
        reg_data = data["regions"].get(reg_key, {})
        for cid, cdata in reg_data.get("channels", {}).items():

            # Apply blacklist filter
            if not ignore_blacklist and cid in STVP_BLACKLIST:
                logging.debug(f"Skipping blacklisted STVP channel: {cid}")
                continue

            channels.append({
                "sid": cdata.get("chno", 0),
                "name": cdata.get("name", "Unknown").strip(),
                "category": cdata.get("group", "Uncategorized").strip(),
                "channel_id": cid,                      # Raw ID for EPG matching
                "logo_url": cdata.get("logo"),
                "url": f"https://jmp2.uk/stvp-{cid}"    # Prefix for stream URL
            })
    return channels

def create_m3u_playlist(channels, output_path):
    """
    Generate an M3U playlist file from channel data.

    Parameters
    ----------
    channels : list of dict
        List of channel metadata dictionaries.
    output_path : str
        File path where the M3U file will be saved.
    """
    if not output_path:
        return
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("#EXTM3U\n")
            for c in channels:
                f.write(f'#EXTINF:-1 tvg-id="{c["channel_id"]}" tvg-chno="{c["sid"]}" '
                        f'tvg-name="{c["name"]}" tvg-logo="{c["logo_url"]}" '
                        f'group-title="{c["category"]}",{c["name"]}\n{c["url"]}\n')
        logging.info(f"M3U created: {output_path}")
    except Exception as e:
        logging.error(f"M3U Error: {e}")

def write_bouquets(bouquet_data, bouquet_dir, reverse=False):
    """
    Write bouquet files and update the central bouquets.tv file.

    Parameters
    ----------
    bouquet_data : dict
        Dictionary where keys are filenames and values are lists of service lines.
    bouquet_dir : str
        Directory path for saving bouquet files.
    reverse : bool, optional
        Whether to sort the bouquet references in reverse alphabetical order.
    """
    bouquets_tv = os.path.join(bouquet_dir, "bouquets.tv")
    references = []

    for filename, lines in bouquet_data.items():
        path = os.path.join(bouquet_dir, filename)
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        references.append(f'#SERVICE 1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "{filename}" ORDER BY bouquet\n')

    if references:
        references.sort(reverse=reverse)
        with open(bouquets_tv, 'a', encoding='utf-8') as f:
            f.writelines(references)
        logging.info(f"Updated bouquets.tv and created {len(references)} bouquet files.")

def process_channels(channels, provider_prefix, tid, service_type, bouquet_dir, conf_dir, channels_file, download_picons, one_bouquet, reverse_bouquets):
    """
    Process channel data to create bouquets and EPG channel maps.

    Parameters
    ----------
    channels : list of dict
        Processed channel data.
    provider_prefix : str
        Prefix for naming generated files.
    tid : str
        Hexadecimal Transponder ID.
    service_type : str
        The ServiceType prefix (e.g., '4097').
    bouquet_dir : str
        Target directory for bouquet files.
    conf_dir : str
        Target directory for XML configuration files.
    channels_file : str
        Name of the generated channels XML file.
    download_picons : bool
        Flag to enable logo list generation.
    one_bouquet : bool
        If True, groups all channels into one bouquet with markers.
    reverse_bouquets : bool
        Whether to sort bouquet references in reverse order.

    Returns
    -------
    list of tuple
        A list of (url, filename) tuples for picon downloads.
    """
    picon_list = []
    bouquet_contents = defaultdict(list)

    # Extract clean provider name for bouquet display
    provider_display = provider_prefix.split('_')[-1]
    
    # Force uppercase TID to adhere to Enigma2 standards
    tid = tid.upper()

    main_filename = f"{provider_prefix}.tv"
    if one_bouquet:
        bouquet_contents[main_filename].append(f"#NAME {provider_display}\n")

    current_marker = None
    for c in channels:
        hex_sid_bouquet = f"{c['sid']:04X}"  # e.g.: 009B
        hex_sid_picon = f"{c['sid']:X}"      # e.g.: 9B

        url_clean = c['url'].replace(':', '%3a')

        picon_name = f"{service_type}_0_1_{hex_sid_picon}_{tid}_0_0_0_0_0".upper()
        
        if download_picons and c['logo_url']:
            picon_url = f"{c['logo_url']}?w=220&h=132"
            picon_list.append((picon_url, f"{picon_name}.png"))

        # Construct Enigma2 service entry
        entry = (f"#SERVICE {service_type}:0:1:{hex_sid_bouquet}:{tid}:0:0:0:0:0:{url_clean}:{c['name']}\n"
                 f"#DESCRIPTION {c['name']}\n")

        # Determine bouquet structure based on user preference
        if one_bouquet:
            if c['category'] != current_marker:
                current_marker = c['category']
                bouquet_contents[main_filename].append(f"#SERVICE 1:64:1:0:0:0:0:0:0:0::{current_marker}\n")
                bouquet_contents[main_filename].append(f"#DESCRIPTION {current_marker}\n")
            bouquet_contents[main_filename].append(entry)
        else:
            cat_fn = f"{provider_prefix}_{normalize_name(c['category'])}.tv"
            if not bouquet_contents[cat_fn]:
                bouquet_contents[cat_fn].append(f"#NAME {provider_display} {c['category']}\n")
            bouquet_contents[cat_fn].append(entry)

    write_bouquets(bouquet_contents, bouquet_dir, reverse=reverse_bouquets)

    # Generate XML channel map sorted alphabetically for EPG mapping
    xml_sort_list = sorted(channels, key=lambda x: x['name'].lower())
    xml_entries = []
    for c in xml_sort_list:
        # Calculate the 4-digit hex SID for the current channel to prevent duplicates
        h_sid = f"{c['sid']:04X}"
        xml_entries.append(
            f'\t<channel id="{c["channel_id"]}">{service_type}:0:1:{h_sid}:{tid}:0:0:0:0:0:http%3a//pluto.tv</channel> \n'
        )

    with open(os.path.join(conf_dir, channels_file), 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<channels>\n')
        f.writelines(xml_entries)
        f.write('</channels>\n')

    logging.info(f"EPG channels file created: {channels_file} ({len(xml_entries)} entries).")
    return picon_list

def download_picons(picon_list, picon_folder, overwrite, post_process=False):
    """
    Download channel logos as picons and optionally apply image processing.

    Parameters
    ----------
    picon_list : list of tuple
        List containing (source_url, target_filename) tuples.
    picon_folder : str
        Local directory path for saving picons.
    overwrite : bool
        Whether to overwrite existing files.
    post_process : bool, optional
        Whether to apply rounded corners to the downloaded images. Default is False.
    """
    if not picon_list:
        return
    os.makedirs(picon_folder, exist_ok=True)
    logging.info(f"Downloading {len(picon_list)} picons...")
    for url, name in picon_list:
        path = os.path.join(picon_folder, name)
        if not os.path.exists(path) or overwrite:
            try:
                with urllib.request.urlopen(url) as r, open(path, 'wb') as f:
                    f.write(r.read())
                # Apply rounded corners if requested
                if post_process:
                    apply_rounded_corners(path)
            except Exception:
                pass

def apply_rounded_corners(image_path):
    """
    Apply rounded corners to an image following Material Design principles.

    Parameters
    ----------
    image_path : str
        Path to the image file to be processed.
    """
    try:
        with Image.open(image_path).convert("RGBA") as img:
            # Calculate radius: ~10% of the smaller dimension for Material feel
            width, height = img.size
            radius = int(min(width, height) * 0.1)
            
            # Create a mask for rounded corners
            mask = Image.new('L', img.size, 0)
            draw = ImageDraw.Draw(mask)
            draw.rounded_rectangle((0, 0, width, height), radius=radius, fill=255)
            
            # Apply mask
            result = Image.new('RGBA', img.size, (0, 0, 0, 0))
            result.paste(img, (0, 0), mask=mask)
            result.save(image_path, "PNG")
    except Exception as e:
        logging.debug(f"Post-processing failed for {image_path}: {e}")

def create_epg_source(conf_dir, epg_source_file, channels_file, provider_name, service_key, langs):
    """
    Create an XMLTV source file for EPGImport.

    Parameters
    ----------
    conf_dir : str
        Directory path for saving the source file.
    epg_source_file : str
        Filename of the generated source XML.
    channels_file : str
        Reference filename of the channels XML.
    provider_name : str
        Display name for the source category.
    service_key : str
        Key for the URL path (e.g., 'PlutoTV' or 'SamsungTVPlus').
    langs : list of str
        List of available language/region codes for the EPG.
    """
    path = os.path.join(conf_dir, epg_source_file)
    base = f"https://i.mjh.nz/{service_key}"
    mirror = f"https://github.com/matthuisman/i.mjh.nz/raw/refs/heads/master/{service_key}"
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n<sources>\n')
            f.write(f'\t<sourcecat sourcecatname="{provider_name} (Matt Huisman)">\n')
            for L in langs:
                f.write(f'\t\t<source type="gen_xmltv" nocheck="1" channels="{channels_file}">\n'
                        f'\t\t\t<description>{provider_name} ({L})</description>\n'
                        f'\t\t\t<url>{base}/{L}.xml.gz</url>\n'
                        f'\t\t\t<url>{mirror}/{L}.xml.gz</url>\n\t\t</source>\n')
            f.write('\t</sourcecat>\n</sources>\n')
        logging.info(f"EPG source file created: {epg_source_file}")
    except Exception as e:
        logging.error(f"EPG Source Error: {e}")

def reload_enigma2():
    """
    Trigger a service list reload via the Enigma2 WebInterface.
    """
    try:
        urllib.request.urlopen("http://127.0.0.1/web/servicelistreload?mode=0", timeout=5)
        logging.info("Enigma2 servicelist reloaded.")
    except URLError:
        logging.warning("Could not reload Enigma2 servicelist (WebIF not reachable).")

def main():
    """
    Orchestrate the script execution flow.
    """
    args = parse_args()
    if args.quiet:
        logging.getLogger().setLevel(logging.ERROR)

    conf_dir, bouquet_dir, picon_folder = get_system_paths(args.picon_folder)
    
    # Collective list for all channels
    all_channels_for_m3u = []

    # Initialize requested services
    services = []
    if args.provider in ["all", "plutotv"]:
        services.append({
            'id': 'plutotv',
            'name': args.plutotv_provider_name,
            'fetch_func': lambda: fetch_plutotv_data(args.plutotv_source, args.plutotv_id_type, args.picon_color),
            'epg_key': 'PlutoTV',
            'langs': PLUTOTV_EPG_LANGS
        })

    if args.provider in ["all", "stvp"]:
        services.append({
            'id': 'stvp',
            'name': args.stvp_provider_name,
            'fetch_func': lambda: fetch_stvp_data(args.stvp_source, args.stvp_region, args.stvp_ignore_blacklist),
            'epg_key': 'SamsungTVPlus',
            'langs': STVP_REGIONS
        })

    for srv in services:
        # Configuration for current provider
        prefix = f"userbouquet.iptv_{srv['name']}"

        # Dynamically select the correct TID based on the service name
        tid_attr = f"{srv['id']}_tid" 
        manual_tid = getattr(args, tid_attr, None)
        tid = manual_tid or hashlib.md5(srv['name'].encode()).hexdigest()[:4]

        c_file, s_file = f"{srv['name']}.channels.xml", f"{srv['name']}.sources.xml"

        logging.info(f"Processing provider: {srv['name']} (TID: {tid})")
        channels = srv['fetch_func']()

        if not channels:
            logging.warning(f"No channels found for {srv['name']}.")
            continue

        # Sort by category/chno
        channels.sort(key=lambda x: (x['category'], x['sid']) if args.one_bouquet else x['sid'])
        for i, c in enumerate(channels, start=1):
            c['sid'] = i

        all_channels_for_m3u.extend(channels)

        if args.playlist_only:
            continue

        clean_old_files(bouquet_dir, conf_dir, prefix, c_file)
        
        do_download = args.download_picons or args.download_overwrite_picons
        picons = process_channels(channels, prefix, tid, args.service_type, bouquet_dir, conf_dir, c_file, 
                                  do_download, args.one_bouquet, args.reverse_bouquets)

        # Determine if post-processing should be applied for this service
        post_process_active = args.picon_post_processing in ["all", srv['id']]

        if do_download:
            download_picons(picons, picon_folder, args.download_overwrite_picons, post_process_active)

        create_epg_source(conf_dir, s_file, c_file, srv['name'], srv['epg_key'], srv['langs'])

    if args.playlist_only:
        create_m3u_playlist(all_channels_for_m3u, args.playlist_only)
    elif args.playlist:
        create_m3u_playlist(all_channels_for_m3u, args.playlist)

    if not args.not_reload and not args.playlist_only:
        reload_enigma2()

if __name__ == "__main__":
    main()
