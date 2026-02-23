#!/usr/bin/env python3

import getpass
import time
import sys
import requests

API = "https://api.github.com"
HEADERS_BASE = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def build_headers(token: str) -> dict:
    return {**HEADERS_BASE, "Authorization": f"token {token}"}


def get_variable(headers: dict, repo: str, name: str):
    url = f"{API}/repos/{repo}/actions/variables/{name}"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return None
    return r.json().get("value")


def count_csv_rows(headers: dict, repo: str) -> int | None:
    url = f"{API}/repos/{repo}/contents/data.csv"
    r = requests.get(url, headers=headers)
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        return None
    import base64
    raw = base64.b64decode(r.json()["content"]).decode()
    lines = [l for l in raw.strip().splitlines() if l.strip()]
    return max(0, len(lines) - 1)


def send_dispatch(headers: dict, repo: str) -> bool:
    url = f"{API}/repos/{repo}/dispatches"
    r = requests.post(url, headers=headers, json={"event_type": "run-bot"})
    return r.status_code == 204


def check_remaining(headers: dict, repo: str, total_rows: int) -> tuple[int, int] | None:
    val = get_variable(headers, repo, "NEXT_ROW")
    if val is None:
        return None
    try:
        next_row = int(val)
    except (ValueError, TypeError):
        return None
    return next_row, total_rows


def fmt_time(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}m {s}s" if m else f"{s}s"


def main():
    print("=" * 50)
    print("  LA28 GitHub Actions Dispatcher")
    print("=" * 50)
    print()

    token = getpass.getpass("GitHub PAT token: ").strip()
    if not token:
        print("Token cannot be empty.")
        sys.exit(1)

    repo = input("Repository (OWNER/REPO): ").strip()
    if "/" not in repo:
        print("Invalid format. Use OWNER/REPO.")
        sys.exit(1)

    interval_str = input("Dispatch interval in seconds [20]: ").strip()
    interval_sec = int(interval_str) if interval_str else 20
    if interval_sec < 5:
        print("Interval must be >= 5 seconds.")
        sys.exit(1)

    headers = build_headers(token)

    print("\nValidating access...", end=" ", flush=True)
    total = count_csv_rows(headers, repo)
    if total is None:
        total_str = input("\nCould not read data.csv (expected if private). Enter total row count: ").strip()
        try:
            total = int(total_str)
        except (ValueError, TypeError):
            print("Invalid row count.")
            sys.exit(1)

    info = check_remaining(headers, repo, total)
    if info is None:
        print("FAILED")
        print("Could not read NEXT_ROW variable. Ensure it exists in repo Settings → Variables.")
        sys.exit(1)

    next_row, total = info
    remaining = max(0, total - next_row)
    print("OK")
    print(f"  Rows processed so far : {next_row}")
    print(f"  Total data rows       : {total}")
    print(f"  Remaining             : {remaining}")
    print(f"  Interval              : every {interval_sec} second(s)")
    print()

    if remaining == 0:
        print("Nothing to do — all rows have been processed.")
        sys.exit(0)

    dispatch_count = 0
    try:
        while True:
            info = check_remaining(headers, repo, total)
            if info is not None:
                next_row, total = info
                remaining = max(0, total - next_row)
                if remaining == 0:
                    print(f"\n All {total} rows processed. Stopping.")
                    break

            dispatch_count += 1
            ts = time.strftime("%H:%M:%S")
            ok = send_dispatch(headers, repo)
            status = "sent" if ok else "FAILED"
            print(f"[{ts}]  Dispatch #{dispatch_count}  |  {status}  |  rows left: {remaining}")

            if not ok:
                print("  Dispatch failed — check your PAT token permissions (needs repo + workflow).")

            wait = interval_sec
            end = time.time() + wait
            while time.time() < end:
                left = int(end - time.time())
                print(f"\r  Next dispatch in {fmt_time(left)}   ", end="", flush=True)
                time.sleep(1)
            print("\r" + " " * 50 + "\r", end="")

    except KeyboardInterrupt:
        print(f"\n\nStopped by user after {dispatch_count} dispatch(es).")
        sys.exit(0)

    print(f"\nDone. Sent {dispatch_count} dispatch(es) total.")


if __name__ == "__main__":
    main()
