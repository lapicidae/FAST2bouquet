#!/usr/bin/env python3
import argparse
import concurrent.futures
import datetime
import glob
import hashlib
import io
import json
import logging
import os
import re
import urllib.parse
import urllib.request
import uuid
from collections import defaultdict
from PIL import Image, ImageDraw
from urllib.error import URLError

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


# --- Internal Configuration ---

# Supported Providers
SUPPORTED_PROVIDERS = ['plutotv', 'rakutentv', 'stvp']

# Playlist Configuration
DEFAULT_M3U_NAME = "iptv_FAST.m3u"

# Samsung TV Plus Specifics
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

# Rakuten TV Specifics
RAKUTEN_CLASSIFICATIONS = {
    "al": 270, "at": 300, "ba": 245, "be": 308, "bg": 269, "ch": 319, "cz": 272,
    "de": 307, "dk": 283, "ee": 288, "es": 5, "fi": 284, "fr": 23, "gr": 279,
    "hr": 302, "ie": 41, "is": 287, "it": 36, "jp": 309, "lt": 290, "lu": 74,
    "me": 259, "mk": 275, "nl": 69, "no": 286, "pl": 277, "pt": 64, "ro": 268,
    "rs": 266, "se": 282, "sk": 273, "uk": 18,
}


# --- Central Provider Configuration ---
#
# This dictionary centralizes all provider-specific metadata for EPG generation,
# M3U metadata (KODi), and channel sourcing.
#
# Logic for field usage:
# - credit:        Default author/source name for the EPG (used in .sources.xml).
# - logo:          URL to the provider's official logo (used for KODi provider-logo tag).
# - type_attr:     Template for the <source> tag attributes in EPGImport sources.
#                  Supports {channels} and {name} placeholders.
# - desc_template: Template for the <description> tag in EPGImport.
#                  Supports {name}, {val} (lowercase), and {val_upper} (uppercase).
# - url_template:  List of URL patterns for providers with consistent naming schemes.
#                  The {val} placeholder is replaced by the region code.
# - channels_tag:  Boolean. If True, a separate <channels> element is created 
#                  instead of using the channels attribute in the <source> tag.
# - regions:       Dictionary for region-specific overrides:
#                  - url:    Direct XMLTV URL (overrides url_template if present).
#                  - credit: Region-specific author (overrides global credit).
PROVIDER_CONFIG = {
    'plutotv': {
        'credit': 'Matt Huisman',
        'logo': 'https://upload.wikimedia.org/wikipedia/commons/thumb/c/c3/Pluto_TV_logo_2024.svg/604px-Pluto_TV_logo_2024.svg.png',
        'type_attr': 'type="gen_xmltv" nocheck="1" channels="{channels}"',
        'url_template': [
            'https://i.mjh.nz/PlutoTV/{val}.xml.gz', 
            'https://github.com/matthuisman/i.mjh.nz/raw/refs/heads/master/PlutoTV/{val}.xml.gz'
        ],
        'desc_template': '{name} ({val_upper})',
        'regions': {
            'all': {},
            'ar': {}, 'br': {}, 'ca': {}, 'cl': {}, 'de': {}, 'dk': {}, 'es': {},
            'fr': {}, 'gb': {}, 'it': {}, 'mx': {}, 'no': {}, 'se': {}, 'us': {}
        }
    },
    'rakutentv': {
        'logo': 'https://upload.wikimedia.org/wikipedia/commons/thumb/e/e5/Rakuten_TV_logo.svg/800px-Rakuten_TV_logo.svg.png',
        'type_attr': 'name="{name}"',
        'desc_template': '{name} ({val_upper})',
        'channels_tag': True,
        'regions': {
            'de': {
                'url': 'https://raw.githubusercontent.com/Fellfresse/Rakuten-DACH-EPG/master/Rakuten_DE_epg.xml',
                'credit': 'Fellfresse'
            },
            'at': {
                'url': 'https://raw.githubusercontent.com/Fellfresse/Rakuten-DACH-EPG/master/Rakuten_AT_epg.xml',
                'credit': 'Fellfresse'
            },
            'ch': {
                'url': 'https://raw.githubusercontent.com/Fellfresse/Rakuten-DACH-EPG/master/Rakuten_CH_epg.xml',
                'credit': 'Fellfresse'
            },
            'uk': {
                'url': 'https://raw.githubusercontent.com/dp247/rakuten-uk-epg/master/epg.xml',
                'credit': 'dp247'
            }
        }
    },
    'stvp': {
        'credit': 'Matt Huisman',
        'logo': 'https://upload.wikimedia.org/wikipedia/commons/thumb/b/bd/Samsung_TV_Plus_logo.svg/406px-Samsung_TV_Plus_logo.svg.png',
        'type_attr': 'type="gen_xmltv" nocheck="1" channels="{channels}"',
        'url_template': [
            'https://i.mjh.nz/SamsungTVPlus/{val}.xml.gz', 
            'https://github.com/matthuisman/i.mjh.nz/raw/refs/heads/master/SamsungTVPlus/{val}.xml.gz'
        ],
        'desc_template': '{name} ({val_upper})',
        'regions': {
            'all': {}, 'at': {}, 'ca': {}, 'ch': {}, 'de': {}, 'es': {},
            'fr': {}, 'gb': {}, 'in': {}, 'it': {}, 'kr': {}, 'us': {}
        }
    }
}


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
    prov_group.add_argument("--provider", default="all", help="Select which service(s) to generate. The order of the list determines the sorting in Enigma2 ('all', 'plutotv', 'rakutentv', 'stvp' or a comma-separated list like 'plutotv,stvp')")

    # PlutoTV group
    plutotv_group = parser.add_argument_group("Pluto TV")
    plutotv_group.add_argument("--plutotv-provider-name", default="PlutoTV", help="Display name and file prefix for Pluto TV")
    plutotv_group.add_argument("--plutotv-tid", help="Manual hex transponder ID (auto-generated from provider name if omitted)")
    plutotv_group.add_argument("--plutotv-source", default="https://boot.pluto.tv", help="Pluto TV API entry point")
    plutotv_group.add_argument("--plutotv-id-type", choices=["id", "slug"], default="id", help="Mapping type for EPG: 'id' (UUID) or 'slug' (human readable)")

    # Rakuten TV group
    rakuten_group = parser.add_argument_group("Rakuten TV")
    rakuten_group.add_argument("--rakutentv-region", choices=list(RAKUTEN_CLASSIFICATIONS.keys()), default="de", help="Regional subset for Rakuten TV. Note: Rakuten TV is strictly geo-blocked; your IP must match the selected region.")
    rakuten_group.add_argument("--rakutentv-provider-name", default="RakutenTV", help="Display name and file prefix for Rakuten TV")
    rakuten_group.add_argument("--rakutentv-tid", help="Manual hex transponder ID (auto-generated from provider name if omitted)")
    rakuten_group.add_argument("--rakutentv-source", default="https://gizmo.rakuten.tv/v3", help="Rakuten TV API base URL")

    # Samsung TV Plus group
    stvp_group = parser.add_argument_group("Samsung TV Plus")
    stvp_group.add_argument("--stvp-region", choices=list(PROVIDER_CONFIG['stvp']['regions'].keys()), default="de", help="Regional subset for Samsung TV Plus")
    stvp_group.add_argument("--stvp-provider-name", default="SamsungTVPlus", help="Display name and file prefix for Samsung TV Plus")
    stvp_group.add_argument("--stvp-tid", help="Manual hex transponder ID (auto-generated from provider name if omitted)")
    stvp_group.add_argument("--stvp-source", default="https://i.mjh.nz/SamsungTVPlus/.channels.json", help="Samsung TV Plus JSON API URL")
    stvp_group.add_argument("--stvp-ignore-blacklist", action="store_true", help="Include all channels, ignoring the internal STVP blacklist")

    # Bouquet selection group
    bouquet_group = parser.add_argument_group("Bouquet options")
    bouquet_group.add_argument("-o", "--one-bouquet", action="store_true", help="Merge all categories with markers into a single bouquet per provider")
    bouquet_group.add_argument("-r", "--reverse-bouquets", action="store_true", help="Sort bouquets in reverse alphabetical order (Z-A)")

    # Output selection group
    playlist_group = parser.add_argument_group("Playlist options")
    playlist_group.add_argument("-p", "--playlist", nargs='?', const='DEFAULT', help="Create M3U playlist(s). Optionally specify an output directory.")
    playlist_group.add_argument("-P", "--playlist-only", nargs='?', const='DEFAULT', help="Create ONLY M3U playlist(s). Optionally specify an output directory.")
    playlist_group.add_argument("-O", "--one-playlist", action="store_true", help=f"Merge all providers into a single '{DEFAULT_M3U_NAME}'.")

    # Picon group
    picon_group = parser.add_argument_group("Picon settings")
    picon_group.add_argument("-d", "--download-picons", action="store_true", help="Download missing picons")
    picon_group.add_argument("-D", "--download-overwrite-picons", action="store_true", help="Download and overwrite existing picons")
    picon_group.add_argument("--picon-colorful", default="plutotv", help="Use colorful picons ('all', 'false', 'plutotv', 'rakutentv' or a comma-separated list like 'plutotv,rakutentv')")
    picon_group.add_argument("--picon-size", default="220x132", help="Target picon size (e.g., 100x60, 220x132, 400x170, 400x240). Format: WIDTHxHEIGHT")
    picon_group.add_argument("--picon-no-resize", dest="picon_resize", action="store_false", default=True, help="Keep original picon dimensions.")
    picon_group.add_argument("--picon-post-processing", default="stvp", help="Enable picon post-processing ('all', 'false', 'plutotv', 'rakutentv', 'stvp' or a comma-separated list like 'rakutentv,stvp')")
    picon_group.add_argument("--picon-folder", help="Custom path to the picon directory (overrides default search order)")

    # Technical group
    tec_group = parser.add_argument_group("Technical configuration")
    tec_group.add_argument("--no-parallel", dest="parallel", action="store_false", default=True, help="Disable parallel processing")
    tec_group.add_argument("--not-reload", action="store_true", help="Do not reload the Enigma2 service list after creating the bouquet")
    tec_group.add_argument("--service-type", default="4097", help="Enigma2 service type: 4097 (GstPlayer). 5001, 5002 and 5003 are used by the ServiceApp plugin and additional players such as ffmpeg + exteplayer3")

    # Advanced group
    # config_group = parser.add_argument_group("Advanced configuration")

    # Global switches
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress info messages, only log errors")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode (saves API responses to JSON files)")

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

def get_stable_sid(unique_id):
    """
    Generate a stable 16-bit integer SID (0-65535) from a provider's unique ID.

    Parameters
    ----------
    unique_id : str or int
        The unique identifier of the channel provided by the source API.

    Returns
    -------
    int
        A deterministic 16-bit integer (0x0000 to 0xFFFF) for Enigma2 service references.
    """
    return int(hashlib.md5(str(unique_id).encode()).hexdigest()[:4], 16)

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

def fetch_plutotv_data(api_url, id_type, picon_color, debug=False):
    """
    Fetch and parse channel data from the Pluto TV JSON APIs.

    Parameters
    ----------
    api_url : str
        The base URL for Pluto TV boot (API entry point).
    id_type : str
        The type of ID to use for tvg-id mapping ('slug' or 'id').
    picon_color : str
        The style of logo to fetch ('color' or 'solid').
    debug : bool, optional
        If True, raw API responses are saved to local JSON files.

    Returns
    -------
    list of dict
        A list containing dictionaries with channel metadata and stream URLs.
    """
    # Fetch app version (Browser-like)
    app_version = 'unknown'
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    try:
        req = urllib.request.Request("https://pluto.tv/", headers={'User-Agent': user_agent})
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8')
            match = re.search(r'name="appVersion"[^>]*content="([^"]+)"', html) or \
                    re.search(r'"appVersion"\s*:\s*"([^"]+)"', html)
            if match:
                app_version = match.group(1)
    except Exception:
        pass

    # Boot sequence
    device_id = str(uuid.uuid1())
    client_time = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

    boot_params = {
        'appName': 'web',
        'appVersion': app_version,
        'clientTime': client_time,
        'deviceDNT': '0',
        'clientId': device_id,
        'clientModelNumber': '1.0.0',
        'clientModelName': 'Chrome',
        'clientModel': 'web',
        'clientType': 'web',
        'deviceVersion': '145.0.0',
        'drmCapabilities': 'widevine:L3',
        'includeExtendedEvents': 'false',
        'serverSideAds': 'false',
        'deviceMake': 'chrome',
        'deviceType': 'web',
        'deviceModel': 'web',
        'notificationVersion': '1',
        'appLaunchCount': '1',
        'lastAppLaunchDate': ''
    }

    boot_url = f"{api_url.rstrip('/')}/v4/start?{urllib.parse.urlencode(boot_params)}"

    try:
        req = urllib.request.Request(boot_url, headers={'User-Agent': user_agent})
        with urllib.request.urlopen(req, timeout=10) as response:
            boot_raw = response.read().decode('utf-8')
            if debug:
                with open("debug_plutotv-boot.json", "w", encoding="utf-8") as f:
                    f.write(boot_raw)
            boot_data = json.loads(boot_raw)

        session_token = boot_data.get('sessionToken')
        servers = boot_data.get('servers', {})
        stitcher_url = (servers.get('stitcher') or servers.get('stitcherDash', '')).rstrip('/')
        channels_url = servers.get('channels', '').rstrip('/')
        region = boot_data.get("session", {}).get("activeRegion", "de").lower()

        if not session_token or not stitcher_url:
            logging.error("Pluto TV: Boot failed.")
            return []
    except Exception as e:
        logging.error(f"Pluto TV boot error: {e}")
        return []

    # Fetch Categories
    category_map = {}
    categories_api = f"{channels_url}/v2/guide/categories"
    try:
        req = urllib.request.Request(categories_api, headers={'Authorization': f'Bearer {session_token}', 'User-Agent': user_agent})
        with urllib.request.urlopen(req, timeout=10) as response:
            cat_raw = response.read().decode('utf-8')
            if debug:
                with open("debug_plutotv-categories.json", "w", encoding="utf-8") as f:
                    f.write(cat_raw)
            cat_json = json.loads(cat_raw)
            # Handle data.data or data directly
            cat_list = cat_json.get("data", cat_json) if isinstance(cat_json, dict) else cat_json
            for cat in cat_list:
                category_map[cat.get("id")] = cat.get("name")
    except Exception:
        pass

    # Fetch Channels
    channels_api = f"{channels_url}/v2/guide/channels?offset=0&limit=1000&sort=number%3Aasc"
    try:
        req = urllib.request.Request(channels_api, headers={'Authorization': f'Bearer {session_token}', 'User-Agent': user_agent})
        with urllib.request.urlopen(req, timeout=10) as response:
            channels_raw = response.read().decode('utf-8')
            if debug:
                with open("debug_plutotv-channels.json", "w", encoding="utf-8") as f:
                    f.write(channels_raw)
            chan_json = json.loads(channels_raw)
            channel_list = chan_json.get("data", chan_json) if isinstance(chan_json, dict) else chan_json
    except Exception as e:
        logging.error(f"Pluto TV channels error: {e}")
        return []

    channels = []
    for item in channel_list:
        _id = item.get("id") or item.get("_id")
        stitched = item.get("stitched", {})

        # Path extraction
        stitched_path = stitched.get("path")
        if not stitched_path:
            paths = stitched.get("paths", [])
            for p in paths:
                if p.get("type") == "hls" or not p.get("type"):
                    stitched_path = p.get("path")
                    break
        if not stitched_path:
            urls = stitched.get("urls", [])
            if urls and urls[0].get("url"):
                stitched_path = urls[0].get("url")

        if not _id or not item.get("isStitched") or not stitched_path:
            continue

        # URL Construction
        # We ensure the URL starts with /v2/stitch...
        clean_path = stitched_path
        if not clean_path.startswith('/v2'):
            clean_path = '/v2' + clean_path

        # Parse existing query params from the path
        parsed_path = urllib.parse.urlparse(clean_path)
        query_params = urllib.parse.parse_qs(parsed_path.query)

        # Add/Override session parameters
        query_params['jwt'] = [session_token]
        query_params['masterJWTPassthrough'] = ['1']

        # Build final stream URL
        new_query = urllib.parse.urlencode(query_params, doseq=True)
        # Combine base, path and new query
        stream_url = f"{stitcher_url}{parsed_path.path}?{new_query}"

        # Category mapping
        cat_ids = item.get("categoryIDs", [])
        category_name = category_map.get(cat_ids[0]) if cat_ids and cat_ids[0] in category_map else "Uncategorized"

        # Logo handling
        images = item.get("images", [])
        c_logo, s_logo = "", ""
        for img in images:
            img_url = img.get("url") or img.get("path")
            if img.get("type") == "colorLogoPNG":
                c_logo = img_url
            elif img.get("type") == "solidLogoPNG":
                s_logo = img_url

        logo_url = (s_logo if picon_color == "solid" else c_logo) or c_logo or s_logo or 'https://images.pluto.tv/channels/default/logo.png'

        channels.append({
            "sid": get_stable_sid(_id),
            "ch_number": item.get("number", 9999),
            "name": item.get("name", "Unknown").strip(),
            "category": category_name.strip(),
            "channel_id": item.get("slug") if id_type == "slug" else _id,
            "logo_url": logo_url,
            "url": stream_url,
            "user_agent": user_agent,
            "region": region
        })

    return channels

def fetch_rakutentv_data(args, region, picon_color):
    """
    Fetch and parse channel data from Rakuten TV API including POST for streams.

    Note: Rakuten TV uses strict geo-blocking based on the client's IP address.

    Parameters
    ----------
    args : argparse.Namespace
        Global arguments containing the rakutentv_source URL.
    region : str
        The region code (e.g., 'de') to fetch data for.
    picon_color : str
        The style of logo to fetch ('color' or 'solid').

    Returns
    -------
    list of dict
        A list containing dictionaries with channel metadata and stream URLs.
    """
    cls_id = RAKUTEN_CLASSIFICATIONS.get(region, 307)
    api_base = args.rakutentv_source
    headers = {
        "Origin": "https://rakuten.tv",
        "Referer": "https://rakuten.tv/",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:98.0) Gecko/20100101 Firefox/98.0",
        "Content-Type": "application/json"
    }

    import urllib.parse
    def _get(path, query_params):
        qs = urllib.parse.urlencode(query_params)
        req = urllib.request.Request(f"{api_base}{path}?{qs}", headers=headers)
        try:
            with urllib.request.urlopen(req) as res:
                return json.loads(res.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code in [403, 401]:
                logging.error(f"Rakuten TV access denied (HTTP {e.code}). This is likely due to Geo-blocking. Your IP must match the '{region}' region.")
            else:
                logging.error(f"Rakuten GET Error: {e}")
            return {}
        except Exception as e:
            logging.error(f"Rakuten GET Error: {e}")
            return {}

    def _post(path, query_params, payload):
        qs = urllib.parse.urlencode(query_params)
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(f"{api_base}{path}?{qs}", data=data, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req) as res:
                return json.loads(res.read().decode('utf-8'))
        except Exception:
            return {}

    query_base = {
        "classification_id": cls_id, "device_identifier": "web", 
        "locale": region, "market_code": region
    }

    cat_data = _get("/live_channel_categories", query_base)
    cc_map = {}
    for cat in cat_data.get("data", []):
        cat_name = cat.get("name", "Uncategorized")
        for ch_id_string in cat.get("live_channels", []):
            cc_map[ch_id_string] = cat_name

    ch_query = query_base.copy()
    ch_query.update({"page": 1, "per_page": 200})
    ch_data = _get("/live_channels", ch_query)

    processed_channels = []
    skipped_count = [0] 
    ch_list = ch_data.get("data", [])

    if not ch_list:
        return processed_channels

    logging.info("Rakuten TV: Found %d channels for region '%s'. Fetching stream URLs...", len(ch_list), region)

    def process_single_rakuten_channel(ch):
        ch_id = ch.get("id")
        langs = ch.get("labels", {}).get("languages", [])
        audio_lang = langs[0].get("id") if langs else "ENG"

        images = ch.get("images", {})
        logo_base = (images.get("artwork_negative", "") or images.get("artwork", "")) if picon_color == "solid" else (images.get("artwork", "") or images.get("artwork_negative", ""))
        logo_url = ""
        if logo_base:
            base_url, ext = os.path.splitext(logo_base)
            logo_url = f"{base_url}-width220{ext}"

        post_query = query_base.copy()
        post_query.update({"device_stream_audio_quality": "2.0", "device_stream_hdr_type": "NONE", "device_stream_video_quality": "FHD", "disable_dash_legacy_packages": False})
        post_payload = {"audio_language": audio_lang, "audio_quality": "2.0", "classification_id": cls_id, "content_id": ch_id, "content_type": "live_channels", "device_serial": "not implemented", "player": "web:HLS-NONE:NONE", "strict_video_quality": False, "subtitle_language": "MIS", "video_type": "stream"}

        stream_res = _post("/avod/streamings", post_query, post_payload)
        s_infos = stream_res.get("data", {}).get("stream_infos", [])
        stream_url = s_infos[0].get("url", "") if s_infos else ""

        if not stream_url:
            skipped_count[0] += 1
            return None

        if '.m3u8' in stream_url:
            stream_url = stream_url.partition('.m3u8')[0] + '.m3u8'

        return {
            "sid": get_stable_sid(ch_id),
            "ch_number": ch.get("channel_number") if ch.get("channel_number") is not None else 999999,
            "name": ch.get("title", "Unknown").strip(),
            "category": cc_map.get(ch_id, "Uncategorized").strip(),
            "channel_id": ch_id,
            "logo_url": logo_url,
            "url": stream_url
        }

    if args.parallel:
        logging.info("Rakuten TV: Fetching stream URLs in parallel (max 10 workers)...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(process_single_rakuten_channel, ch_list))
            processed_channels = [r for r in results if r is not None]
    else:
        logging.info("Rakuten TV: Fetching stream URLs sequentially...")
        for ch in ch_list:
            res = process_single_rakuten_channel(ch)
            if res:
                processed_channels.append(res)

    if skipped_count[0] > 0:
        logging.info("Rakuten TV: %d channels skipped (Geo-blocked/No stream/IP blocked).", skipped_count[0])

    return processed_channels

def fetch_stvp_data(api_url, region, picon_color, ignore_blacklist=False):
    """
    Fetch and parse channel data from the Samsung TV Plus JSON API.

    Parameters
    ----------
    api_url : str
        The URL to the Samsung TV Plus JSON API.
    region : str
        The region code to filter channels.
    picon_color : str
        Style of logo (currently placeholder for STVP consistency).
    ignore_blacklist : bool, optional
        If True, the internal STVP_BLACKLIST will be ignored.

    Returns
    -------
    list of dict
        A list containing dictionaries with channel metadata and stream URLs.
    """
    default_ua = 'okhttp/4.12.0'
    try:
        # Initial request to get the JSON data
        req = urllib.request.Request(api_url, headers={'User-Agent': default_ua})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))

            # Extract dynamic User-Agent from API response
            api_ua = data.get("headers", {}).get("user-agent", default_ua)
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

            api_ua = data.get("headers", {}).get("user-agent", default_ua) #

            channels.append({
                "sid": get_stable_sid(cid),
                "ch_number": cdata.get("chno") if cdata.get("chno") is not None else 999999,
                "name": cdata.get("name", "Unknown").strip(),
                "category": cdata.get("group", "Uncategorized").strip(),
                "channel_id": cid,
                "logo_url": cdata.get("logo"),
                "url": f"https://jmp2.uk/stvp-{cid}",
                "user_agent": api_ua
            })
    return channels

def create_m3u_playlist(channels, output_file, epg_urls=None):
    """
    Create an M3U playlist file with optional x-tvg-url and KODi provider tags.

    Parameters
    ----------
    channels : list of dict
        The list of channel dictionaries.
    output_file : str
        The full path and filename for the M3U.
    epg_urls : list of str, optional
        List of XMLTV URLs to include in the header.
    """
    try:
        # Ensure the target directory exists
        target_dir = os.path.dirname(os.path.abspath(output_file))
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            header = "#EXTM3U"
            if epg_urls:
                unique_urls = ",".join(list(dict.fromkeys(filter(None, epg_urls))))
                header += f' x-tvg-url="{unique_urls}"'
            f.write(f"{header}\n")

            for c in channels:
                logo = c.get('logo_url', '')
                group = c.get('category', 'Uncategorized')
                chno = c.get('m3u_chno', 0)
                ua = c.get('user_agent')

                # Provider Infos for KODi (IPTV Simple PVR)
                p_id = c.get('provider_id')
                p_cfg = PROVIDER_CONFIG.get(p_id, {})
                p_name = c.get('provider_name', 'Other')
                p_logo = p_cfg.get('logo', '')

                f.write(f'#EXTINF:-1 tvg-id="{c["channel_id"]}" tvg-chno="{chno}" '
                        f'tvg-logo="{logo}" group-title="{group}" '
                        f'provider="{p_name}" provider-type="iptv" provider-logo="{p_logo}",'
                        f'{c["name"]}\n')
                if ua:
                    f.write(f'#EXTVLCOPT:http-user-agent={ua}\n')
                f.write(f'{c["url"]}\n')
        logging.info(f"M3U playlist created: {output_file}")
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

    # Sort filenames to ensure consistent order in bouquets.tv
    filenames = sorted(bouquet_data.keys(), reverse=reverse)
    references = []

    for filename in filenames:
        lines = bouquet_data[filename]
        path = os.path.join(bouquet_dir, filename)
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        references.append(f'#SERVICE 1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "{filename}" ORDER BY bouquet\n')

    if references:
        with open(bouquets_tv, 'a', encoding='utf-8') as f:
            f.writelines(references)
        logging.info(f"Updated bouquets.tv and created {len(references)} bouquet files.")

def process_channels(channels, provider_prefix, tid, service_type, bouquet_dir, conf_dir, channels_file, download_picons, one_bouquet, reverse_bouquets, picon_size):
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
    picon_size : str
        Target picon size from args.picon_size (e.g. '220x132').

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

    # Extract dimensions for providers that support URL-based resizing
    try:
        width, height = picon_size.lower().split('x')
    except ValueError:
        width, height = "220", "132"

    for c in channels:
        hex_sid_bouquet = f"{c['sid']:04X}"  # e.g.: 009B
        hex_sid_picon = f"{c['sid']:X}"      # e.g.: 9B

        url_clean = c['url'].replace(':', '%3a')

        ua_val = c.get('user_agent') #
        ua_suffix = f"#User-Agent={ua_val}" if ua_val else "" #
        url_clean = (c['url'] + ua_suffix).replace(':', '%3a') #

        picon_name = f"{service_type}_0_1_{hex_sid_picon}_{tid}_0_0_0_0_0".upper()

        if download_picons and c['logo_url']:
            picon_url = c['logo_url']

            # Only append resizing parameters for PlutoTV URLs
            if "pluto.tv" in picon_url:
                # Append or update width/height parameters
                separator = "&" if "?" in picon_url else "?"
                picon_url = f"{picon_url}{separator}w={width}&h={height}"

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

def download_picons(picons, picon_folder, overwrite, post_process_active, resize_active, target_size, is_parallel):
    """
    Download and process picons in RAM with unified parameter handling.

    Parameters
    ----------
    picons : list of tuple
        List of (url, filename) tuples.
    picon_folder : str
        Local path for saving picons.
    overwrite : bool
        Overwrite existing files.
    post_process_active : bool
        Enable rounded corners.
    resize_active : bool
        Enable resizing and canvas padding.
    target_size : str
        Target resolution (e.g., '220x132').
    is_parallel : bool
        Enable multi-threaded downloads.
    """
    if not picons:
        return

    os.makedirs(picon_folder, exist_ok=True)

    def fetch_and_process(p_url, p_path):
        if not overwrite and os.path.exists(p_path):
            return False
        try:
            req = urllib.request.Request(p_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                img_data = io.BytesIO(response.read())

            with Image.open(img_data) as img:
                img = img.convert("RGBA")

                # Rounding logic
                if post_process_active:
                    img = apply_rounded_corners(img)

                # Resizing logic
                if resize_active:
                    img = process_image(img, target_size)

                # Final 8-bit optimization and storage write
                img = img.quantize(colors=256, method=2).convert("RGBA")
                img.save(p_path, "PNG", optimize=True)

            return True
        except Exception as e:
            logging.debug(f"Picon error ({p_url}): {e}")
            return False

    tasks = [(url, os.path.join(picon_folder, fn)) for url, fn in picons if url.startswith('http')]
    if not tasks:
        return

    count = 0
    if is_parallel:
        logging.info("Downloading %d picons in parallel...", len(tasks))
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(fetch_and_process, url, path): url for url, path in tasks}
            for future in concurrent.futures.as_completed(futures):
                if future.result():
                    count += 1
    else:
        logging.info("Downloading %d picons sequentially...", len(tasks))
        for url, path in tasks:
            if fetch_and_process(url, path):
                count += 1

    if count > 0:
        logging.info("Successfully saved %d picons to flash.", count)

def process_image(img, target_size_str):
    """
    Resize an Image object in memory using a transparent canvas to match aspect ratio.

    Parameters
    ----------
    img : PIL.Image.Image
        The image object to be processed.
    target_size_str : str
        Target resolution string in 'WIDTHxHEIGHT' format (e.g., '220x132').

    Returns
    -------
    PIL.Image.Image
        The processed and resized image object.
    """
    try:
        t_w, t_h = map(int, target_size_str.lower().split('x'))
        target_res = (t_w, t_h)
        target_ratio = t_w / t_h

        orig_w, orig_h = img.size
        current_ratio = orig_w / orig_h

        # Calculate canvas dimensions to prevent stretching
        if current_ratio > target_ratio:
            canvas_w = orig_w
            canvas_h = int(orig_w / target_ratio)
        else:
            canvas_h = orig_h
            canvas_w = int(orig_h * target_ratio)

        # Create transparent canvas and center the original image
        canvas = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        offset = ((canvas_w - orig_w) // 2, (canvas_h - orig_h) // 2)
        canvas.paste(img, offset)

        # Resize using LANCZOS for best quality
        return canvas.resize(target_res, Image.Resampling.LANCZOS)
    except Exception:
        # Fallback to original image if processing fails
        return img

def apply_rounded_corners(img):
    """
    Apply rounded corners to an Image object using Material Design principles.

    Parameters
    ----------
    img : PIL.Image.Image
        The image object to be processed.

    Returns
    -------
    PIL.Image.Image
        The image object with rounded corners applied.
    """
    try:
        width, height = img.size
        # Radius: ~10% of the smaller dimension for a balanced look
        radius = int(min(width, height) * 0.1)

        # Create a transparency mask for the corners
        mask = Image.new('L', (width, height), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, width, height), radius=radius, fill=255)

        # Apply the mask to a new transparent canvas
        output = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        output.paste(img, (0, 0), mask=mask)
        return output
    except Exception as e:
        logging.debug(f"Rounding failed in RAM: {e}")
        return img

def get_epg_urls(p_id, regions):
    """
    Extract EPG URLs from the central configuration for specific regions.

    Parameters
    ----------
    p_id : str
        The provider identifier (e.g., 'plutotv', 'stvp', 'rakutentv').
    regions : str or list of str
        A single region code or a list of codes to process.
    """
    urls = []
    cfg = PROVIDER_CONFIG.get(p_id, {})
    allowed = list(cfg.get('regions', {}).keys())

    region_list = [regions] if isinstance(regions, str) else regions

    for r in region_list:
        if r == 'all':
            for sub_r in allowed:
                if sub_r != 'all':
                    urls.extend(get_epg_urls(p_id, sub_r))
            continue

        if r not in allowed:
            logging.warning(f"EPG region '{r}' not supported for provider '{p_id}'.")
            continue

        if p_id == 'rakutentv':
            u = cfg.get('regions', {}).get(r, {}).get('url')
            if u:
                urls.append(u)
        else:
            templates = cfg.get('url_template', [])
            urls.extend([t.format(val=r) for t in templates])

    return list(dict.fromkeys(urls))

def generate_epg_source(conf_dir, source_file, channels_file, provider_id, provider_name, values):
    """
    Generate an XMLTV source file for EPGImport based on central configuration.

    Parameters
    ----------
    conf_dir : str
        Directory path for saving the source file.
    source_file : str
        Name of the source XML file to create.
    channels_file : str
        Name of the channels XML file reference.
    provider_id : str
        Internal ID of the provider.
    provider_name : str
        Display name of the provider.
    values : list or dict
        List of regions or dictionary with region details.
    """
    cfg = PROVIDER_CONFIG.get(provider_id)
    if not cfg:
        logging.error(f"No EPG configuration found for provider ID: {provider_id}")
        return

    # Prepare region mapping for lookup
    region_avail = cfg.get('regions', {})

    # Identify the first valid region to extract a credit/author
    val_list = values if isinstance(values, list) else list(values.keys())
    first_val = next((v for v in val_list if v != 'all'), None)

    # PRIORITY: 1. Region-specific credit -> 2. Global provider credit -> 3. Unknown
    credit = 'Unknown'
    if first_val and first_val in region_avail:
        credit = region_avail[first_val].get('credit') or cfg.get('credit', 'Unknown')
    else:
        credit = cfg.get('credit', 'Unknown')

    source_path = os.path.join(conf_dir, source_file)
    try:
        with open(source_path, 'w', encoding='utf-8') as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<sources>\n')
            f.write(f'    <sourcecat sourcecatname="{provider_name} ({credit})">\n')

            for val in values:
                desc = cfg['desc_template'].format(name=provider_name, val=val, val_upper=val.upper())
                attr = cfg['type_attr'].format(name=provider_name, channels=channels_file)

                f.write(f'\t\t<source {attr}>\n')
                f.write(f'\t\t\t<description>{desc}</description>\n')

                # Build URL(s)
                if provider_id == 'rakutentv':
                    reg_url = cfg.get('regions', {}).get(val, {}).get('url')
                    if reg_url:
                        f.write(f'\t\t\t<url>{reg_url}</url>\n')
                else:
                    for tmpl in cfg['url_template']:
                        f.write(f'\t\t\t<url>{tmpl.format(val=val)}</url>\n')

                # Apply explicit channels tag if configured (for Rakuten compatibility)
                if cfg.get('channels_tag'):
                    f.write(f'\t\t\t<channels>{channels_file}</channels>\n')

                f.write('\t\t</source>\n')

            f.write('\t</sourcecat>\n</sources>\n')
        logging.info(f"EPG source file created: {source_file}")
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

    # Parse requested providers from string
    provider_setting = args.provider.lower()
    selected_providers = [x.strip() for x in provider_setting.split(',')]

    # Validation of providers
    if "all" not in selected_providers:
        invalid_providers = [p for p in selected_providers if p not in SUPPORTED_PROVIDERS]
        if invalid_providers:
            logging.error(f"Unknown provider(s): {', '.join(invalid_providers)}")
            logging.info(f"Available providers are: {', '.join(SUPPORTED_PROVIDERS)} or 'all'")
            return

    # Initialize requested services
    services = []

    if "all" in selected_providers or "plutotv" in selected_providers:
        services.append({
            'id': 'plutotv',
            'name': args.plutotv_provider_name,
            'fetch_func': lambda mode: fetch_plutotv_data(args.plutotv_source, args.plutotv_id_type, mode, args.debug),
            'epg_func': lambda c_file, s_file, srv_name: generate_epg_source(conf_dir, s_file, c_file, 'plutotv', srv_name, PROVIDER_CONFIG['plutotv']['regions'])
        })

    if "all" in selected_providers or "rakutentv" in selected_providers:
        services.append({
            'id': 'rakutentv',
            'name': args.rakutentv_provider_name,
            'fetch_func': lambda mode: fetch_rakutentv_data(args, args.rakutentv_region, mode),
            'epg_func': lambda c_file, s_file, srv_name: generate_epg_source(conf_dir, s_file, c_file, 'rakutentv', srv_name, [args.rakutentv_region])
        })

    if "all" in selected_providers or "stvp" in selected_providers:
        services.append({
            'id': 'stvp',
            'name': args.stvp_provider_name,
            'fetch_func': lambda mode: fetch_stvp_data(args.stvp_source, args.stvp_region, mode, args.stvp_ignore_blacklist),
            'epg_func': lambda c_file, s_file, srv_name: generate_epg_source(conf_dir, s_file, c_file, 'stvp', srv_name, PROVIDER_CONFIG['stvp']['regions'])
        })

    # Sort services based on the order in --provider or apply reverse if requested
    if args.reverse_bouquets:
        services.reverse()
    elif provider_setting != "all":
        # Ensure the order matches the comma-separated list in --provider
        services.sort(key=lambda s: selected_providers.index(s['id']) if s['id'] in selected_providers else 99)

    for srv in services:
        # Configuration for current provider
        prefix = f"userbouquet.iptv_{srv['name']}"

        # Dynamically select the correct TID based on the service name
        tid_attr = f"{srv['id']}_tid" 
        manual_tid = getattr(args, tid_attr, None)
        tid = manual_tid or hashlib.md5(srv['name'].encode()).hexdigest()[:4]

        c_file, s_file = f"{srv['name']}.channels.xml", f"{srv['name']}.sources.xml"

        # --- Picon Color Logic ---
        # Parse the comma-separated list to decide if this provider gets colorful picons.
        colorful_setting = args.picon_colorful.lower()
        colorful_list = [x.strip() for x in colorful_setting.split(',')]
        is_colorful = "all" in colorful_list or srv['id'] in colorful_list
        picon_mode = "color" if is_colorful else "solid"

        logging.info(f"Processing provider: {srv['name']} (TID: {tid}) [Picon Mode: {picon_mode}]")

        # Execute the fetch function with the determined picon mode
        channels = srv['fetch_func'](picon_mode)

        if not channels:
            if srv['id'] == 'rakutentv':
                logging.error(f"!!! {srv['name']}: No streamable channels found.")
                logging.error(f"Your IP must be physically located in the region '{args.rakutentv_region}'.")
                logging.error("The API found the channel names, but refused to provide the video streams.")
            else:
                logging.warning(f"No channels found for {srv['name']}.")
            continue

        # Sorting: 
        # 1. Category (alphabetical)
        # 2. Original channel number (ascending, 999999 as end fallback)
        # 3. Name (alphabetical, if numbers are the same)
        channels.sort(key=lambda x: (
            x.get('category', 'Uncategorized').lower(),
            x.get('ch_number', 999999),
            x.get('name', '').lower()
        ))

        # Sequential numbering and provider tagging for M3U
        for c in channels:
            c['provider_name'] = srv['name']
            c['provider_id'] = srv['id']

        all_channels_for_m3u.extend(channels)

        if args.playlist_only:
            continue

        clean_old_files(bouquet_dir, conf_dir, prefix, c_file)

        do_download = args.download_picons or args.download_overwrite_picons
        picons = process_channels(
            channels, prefix, tid, args.service_type, bouquet_dir, conf_dir, c_file, 
            do_download, args.one_bouquet, args.reverse_bouquets, args.picon_size
        )

        # --- Picon Post-Processing Logic ---
        # Determine if rounded corners should be applied for this specific provider.
        pp_setting = args.picon_post_processing.lower()
        pp_list = [x.strip() for x in pp_setting.split(',')]
        post_process_active = "all" in pp_list or srv['id'] in pp_list

        if do_download:
            download_picons(
                picons, 
                picon_folder, 
                args.download_overwrite_picons, 
                post_process_active, 
                args.picon_resize, 
                args.picon_size, 
                args.parallel
            )

        srv['epg_func'](c_file, s_file, srv['name'])

   # --- Playlist Creation Logic ---
    # Merge both arguments into a single variable for path evaluation
    playlist_arg = args.playlist_only or args.playlist

    if playlist_arg:
        # Determine the target folder and handle directory creation
        if playlist_arg != 'DEFAULT' and not playlist_arg.endswith('.m3u'):
            playlist_folder = playlist_arg
            os.makedirs(playlist_folder, exist_ok=True)
        else:
            # Fallback to system default paths if 'DEFAULT' or filename is provided
            _, playlist_folder, _ = get_system_paths(None)

        if args.one_playlist:
            # If a filename was provided as an argument, use it; otherwise use default
            if playlist_arg.endswith('.m3u'):
                full_path = playlist_arg if os.path.isabs(playlist_arg) else os.path.join(playlist_folder, os.path.basename(playlist_arg))
            else:
                full_path = os.path.join(playlist_folder, DEFAULT_M3U_NAME)
            # All-In-One Logic
            full_path = playlist_arg if playlist_arg.endswith('.m3u') else os.path.join(playlist_folder, DEFAULT_M3U_NAME)
            all_epg_urls = []

            is_all = "all" in selected_providers

            if is_all or "plutotv" in selected_providers:
                pluto_channels = [c for c in all_channels_for_m3u if c.get('provider_id') == 'plutotv']
                if pluto_channels:
                    region = pluto_channels[0].get('region')
                    if region:
                        all_epg_urls.extend(get_epg_urls('plutotv', region))

            if is_all or "stvp" in selected_providers:
                all_epg_urls.extend(get_epg_urls('stvp', args.stvp_region))

            if is_all or "rakutentv" in selected_providers:
                all_epg_urls.extend(get_epg_urls('rakutentv', args.rakutentv_region))

            for i, c in enumerate(all_channels_for_m3u, start=1):
                c['m3u_chno'] = i
            create_m3u_playlist(all_channels_for_m3u, full_path, all_epg_urls)
        else:
            # Separate Files Logic: Create one file per provider in the determined folder
            from collections import OrderedDict
            provider_groups = OrderedDict()
            for c in all_channels_for_m3u:
                p_id = c.get('provider_id')
                if p_id not in provider_groups:
                    provider_groups[p_id] = {'name': c.get('provider_name'), 'channels': []}
                provider_groups[p_id]['channels'].append(c)

            for p_id, group_data in provider_groups.items():
                p_name = group_data['name']
                p_channels = group_data['channels']
                filename = f"iptv_{p_name}.m3u"
                full_path = os.path.join(playlist_folder, filename)

                # Fetch URLs based on the stored provider_id
                p_urls = []
                if p_id == 'plutotv':
                    region = p_channels[0].get('region') if p_channels else None
                    if region:
                        p_urls = get_epg_urls('plutotv', region)
                elif p_id == 'stvp':
                    p_urls = get_epg_urls('stvp', args.stvp_region)
                elif p_id == 'rakutentv':
                    p_urls = get_epg_urls('rakutentv', args.rakutentv_region)

                for i, c in enumerate(p_channels, start=1):
                    c['m3u_chno'] = i
                create_m3u_playlist(p_channels, full_path, p_urls)

    if not args.not_reload and not args.playlist_only:
        reload_enigma2()

if __name__ == "__main__":
    main()
