"""Acquire the annual NSE Clearing capital-market settlement-holiday notices."""

from pathlib import Path
import hashlib

import requests


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "evidence" / "settlement_official"
NOTICE_IDS = {
    2015: "CMPT28438", 2016: "CMPT31421", 2017: "CMPT33820",
    2018: "CMPT36634", 2019: "CMPT39791", 2020: "CMPT42962",
    2021: "CMPT46687", 2022: "CMPT50630", 2023: "CMPT54855",
}
AMENDMENT_IDS = ["CMPT34182", "CMPT37310"]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for year, notice in list(NOTICE_IDS.items()) + [("amendment", item) for item in AMENDMENT_IDS]:
        url = f"https://archives.nseindia.com/content/circulars/{notice}.pdf"
        path = OUT / f"{notice}.pdf"
        if not path.exists():
            response = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise ValueError(f"Not a PDF: {url}")
            path.write_bytes(response.content)
        print(year, notice, path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest(), url)


if __name__ == "__main__":
    main()
