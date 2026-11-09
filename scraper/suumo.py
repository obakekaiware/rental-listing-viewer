"""SUUMO (https://suumo.jp) rental listing scraper.

Scope and etiquette, please read before changing behavior:
- Only fetches the public HTML search-result pages under /chintai/<pref>/<city>/
  (e.g. /chintai/tokyo/sc_musashino/). These paths are NOT in SUUMO's
  robots.txt disallow list for a generic user-agent.
- Avoids query parameters SUUMO's robots.txt DOES disallow for everyone
  (`sort=`, `cinm=`, `snetid=`, `rnTmp=`, `rnekTmp=`) - sorting is done
  locally in the GUI instead.
- Waits `request_delay_seconds` between requests (see config.json) and stops
  as soon as a page returns no listings, so it never hammers the site or
  loops forever.
- Intended for a single person's own apartment search at low frequency, not
  for bulk redistribution or commercial use.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://suumo.jp"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config.example.json"
DATA_PATH = PROJECT_ROOT / "data" / "listings.json"


@dataclass
class Listing:
    id: str
    building_name: str
    address: str
    town: str
    stations: list[str]
    age_text: str
    stories_text: str
    floor: str
    rent_yen: Optional[int]
    admin_fee_yen: Optional[int]
    deposit_yen: Optional[int]
    gratuity_yen: Optional[int]
    madori: str
    menseki_m2: Optional[float]
    detail_url: str


def load_config() -> dict:
    # config.json is your personal (git-ignored) copy; fall back to the
    # committed example so a fresh clone still runs.
    path = CONFIG_PATH if CONFIG_PATH.exists() else EXAMPLE_CONFIG_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)["suumo"]


def _yen_from_text(text: str) -> Optional[int]:
    text = text.strip().replace("円", "")
    if not text or text == "-":
        return None
    if "万" in text:
        try:
            return round(float(text.replace("万", "")) * 10000)
        except ValueError:
            return None
    try:
        return int(text)
    except ValueError:
        return None


def _menseki_from_text(text: str) -> Optional[float]:
    text = text.replace("m2", "").replace("m²", "").replace("㎡", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def fetch_page(session: requests.Session, search_path: str, params: list[tuple[str, str]]) -> str:
    resp = session.get(urljoin(BASE_URL, search_path), params=params, timeout=20)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def _match_town(address: str, target_towns: list[str]) -> Optional[str]:
    for town in target_towns:
        if town in address:
            return town
    return None


def parse_listings(html: str, target_towns: Optional[list[str]] = None) -> list[Listing]:
    """Parse every listing row on one search-result page.

    Every row on the page is returned (needed so the caller can tell "end of
    pagination" apart from "no rows matched my town filter"). If
    `target_towns` is given, each listing's `town` field is set to whichever
    entry matched its address, or left empty if none did - filtering that
    list down is the caller's job.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[Listing] = []

    for building in soup.select("div.cassetteitem"):
        name_el = building.select_one(".cassetteitem_content-title")
        building_name = name_el.get_text(strip=True) if name_el else ""

        col1 = building.select_one(".cassetteitem_detail-col1")
        address = col1.get_text(strip=True) if col1 else ""

        town = _match_town(address, target_towns) if target_towns else None

        col2 = building.select_one(".cassetteitem_detail-col2")
        stations = (
            [d.get_text(strip=True) for d in col2.select(".cassetteitem_detail-text")]
            if col2
            else []
        )

        col3_divs = building.select(".cassetteitem_detail-col3 > div")
        age_text = col3_divs[0].get_text(strip=True) if len(col3_divs) > 0 else ""
        stories_text = col3_divs[1].get_text(strip=True) if len(col3_divs) > 1 else ""

        for row in building.select("tr.js-cassette_link"):
            tds = row.select("td")
            floor = tds[2].get_text(strip=True) if len(tds) > 2 else ""

            rent_el = row.select_one(".cassetteitem_price--rent")
            admin_el = row.select_one(".cassetteitem_price--administration")
            deposit_el = row.select_one(".cassetteitem_price--deposit")
            gratuity_el = row.select_one(".cassetteitem_price--gratuity")
            madori_el = row.select_one(".cassetteitem_madori")
            menseki_el = row.select_one(".cassetteitem_menseki")
            link_el = row.select_one("a.js-cassette_link_href")

            detail_url = (
                urljoin(BASE_URL, link_el["href"]) if link_el and link_el.has_attr("href") else ""
            )
            listing_id = detail_url.split("jnc_")[-1].split("/")[0] if "jnc_" in detail_url else detail_url

            results.append(
                Listing(
                    id=listing_id,
                    building_name=building_name,
                    address=address,
                    town=town or "",
                    stations=stations,
                    age_text=age_text,
                    stories_text=stories_text,
                    floor=floor,
                    rent_yen=_yen_from_text(rent_el.get_text() if rent_el else ""),
                    admin_fee_yen=_yen_from_text(admin_el.get_text() if admin_el else ""),
                    deposit_yen=_yen_from_text(deposit_el.get_text() if deposit_el else ""),
                    gratuity_yen=_yen_from_text(gratuity_el.get_text() if gratuity_el else ""),
                    madori=madori_el.get_text(strip=True) if madori_el else "",
                    menseki_m2=_menseki_from_text(menseki_el.get_text() if menseki_el else ""),
                    detail_url=detail_url,
                )
            )

    return results


ProgressCallback = Callable[[int, int], None]


def scrape_all(progress_cb: Optional[ProgressCallback] = None) -> list[dict]:
    config = load_config()
    md_codes = list(config["madori_codes"].values())
    page_size = config.get("page_size", 50)
    max_pages = config.get("max_pages", 60)
    delay = config.get("request_delay_seconds", 2.0)
    search_path = config["search_path"]
    target_towns = config.get("target_towns") or []

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    all_listings: dict[str, Listing] = {}
    for page in range(1, max_pages + 1):
        params: list[tuple[str, str]] = [("md", code) for code in md_codes]
        params.append(("pc", str(page_size)))
        if page > 1:
            params.append(("page", str(page)))

        html = fetch_page(session, search_path, params)
        listings = parse_listings(html, target_towns)
        if not listings:
            # An empty page means we've paged past the last result, not that
            # nothing matched target_towns (that's handled below instead).
            break

        for listing in listings:
            if target_towns and not listing.town:
                continue
            all_listings[listing.id] = listing

        if progress_cb:
            progress_cb(page, len(all_listings))

        if page < max_pages:
            time.sleep(delay)

    return [asdict(v) for v in all_listings.values()]


def save_listings(listings: list[dict]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(listings),
        "listings": listings,
    }
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main() -> None:
    def progress(page: int, total: int) -> None:
        print(f"  page {page}: {total} 件取得済み", file=sys.stderr)

    print("SUUMO から物件情報を取得中...", file=sys.stderr)
    listings = scrape_all(progress_cb=progress)
    save_listings(listings)
    print(f"完了: {len(listings)} 件を {DATA_PATH} に保存しました", file=sys.stderr)


if __name__ == "__main__":
    main()
