import re
import requests
from bs4 import BeautifulSoup
from notam_db import save_faa_activity
from notam_logging import logger

url = "https://www.fly.faa.gov/adv/adv_spt"

def parse_faa_advisory():
    logger.info("Fetching FAA advisory from %s", url)

    html = requests.get(url, timeout=30).text
    soup = BeautifulSoup(html, "html.parser")

    text = soup.get_text("\n")

    # Extract the launch block from either advisory layout.
    launch_block_patterns = [
        r"PLANNED LAUNCH/REENTRY:\s*(.*?)(?:FLIGHT CHECK\(S\):|VIP MOVEMENT\(S\):|$)",
        r"AIRSPACE FLOW PROGRAM\(S\) PLANNED:\s*(?:NONE\s*)?(.*?)(?:FLIGHT CHECK\(S\):|VIP MOVEMENT\(S\):|$)",
    ]

    block = None
    for pattern in launch_block_patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            block = match.group(1)
            break

    if not block:
        logger.error("Launch section not found in the FAA advisory")
        raise RuntimeError("Launch section not found")

    logger.info("Launch section found, parsing launches")

    # Parse launches
    launches = []
    current = None
    launch_started = False

    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue

        if line == "NONE":
            continue

        if line.startswith("PRIMARY:"):
            if not current:
                continue
            current["primary_window"] = line.replace("PRIMARY:", "").strip()

        elif line.startswith("BACKUP:"):
            if not current:
                continue
            current["backup_window"] = line.replace("BACKUP:", "").strip()

        else:
            if not launch_started and "," not in line:
                continue

            # New launch entry
            if current:
                launches.append(current)

            current = {
                "mission": line,
                "primary_window": None,
                "backup_window": None
            }
            launch_started = True

    if current:
        launches.append(current)
    
    logger.info("Parsed %d launches from the FAA advisory", len(launches))
    # Save to DB
    for launch in launches:
        save_faa_activity(launch)
