"""Download the public nycflights13 CSVs (no auth) and verify them against pinned checksums.

Source: Rdatasets mirror of the R package nycflights13 (public domain US DOT/BTS + NOAA data).
Usage: python scripts/fetch_data.py [--update-checksums]
"""
import hashlib
import sys
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/vincentarelbundock/Rdatasets/master/csv/nycflights13/"
TABLES = ["flights", "airlines", "airports", "weather", "planes"]
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
CHECKSUMS = RAW.parent / "checksums.txt"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for t in TABLES:
        dest = RAW / f"{t}.csv"
        if not dest.exists():
            print(f"downloading {t}.csv")
            urllib.request.urlretrieve(BASE + f"{t}.csv", dest)
    sums = {t: sha256(RAW / f"{t}.csv") for t in TABLES}
    if "--update-checksums" in sys.argv or not CHECKSUMS.exists():
        CHECKSUMS.write_text("".join(f"{h}  {t}.csv\n" for t, h in sums.items()))
        print("wrote", CHECKSUMS)
        return
    expected = dict(line.split()[::-1] for line in CHECKSUMS.read_text().splitlines())
    bad = [f for f, h in expected.items() if sums[f[:-4]] != h]
    if bad:
        sys.exit(f"checksum mismatch: {bad}")
    print("all files match pinned checksums")


if __name__ == "__main__":
    main()
