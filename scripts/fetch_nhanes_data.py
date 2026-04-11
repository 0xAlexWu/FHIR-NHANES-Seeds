#!/usr/bin/env python3
from __future__ import annotations

import argparse

from nhanes_common import DEFAULT_CYCLE, ensure_standard_directories, get_cycle_config, local_paths_for_source, source_urls, download_url


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download the first-pass NHANES source files and documentation.")
    parser.add_argument("--cycle", default=DEFAULT_CYCLE, help="NHANES cycle label to fetch.")
    parser.add_argument("--force", action="store_true", help="Re-download files even when they already exist.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_standard_directories(args.cycle)
    config = get_cycle_config(args.cycle)

    for source in config.files:
        urls = source_urls(args.cycle, source)
        paths = local_paths_for_source(args.cycle, source)
        download_url(urls["xpt"], paths["xpt"], force=args.force)
        download_url(urls["doc"], paths["doc"], force=args.force)
        print(f"fetched {source.file_code} -> {paths['xpt']}")


if __name__ == "__main__":
    main()
