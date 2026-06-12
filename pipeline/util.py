"""Small shared helpers for the pipeline."""

import sys
import time

import requests

USER_AGENT = "akl-perils-3d/0.1 (open-data proof of concept; github.com/wikkiwokka/akl-perils-3d)"


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def get_with_retry(s: requests.Session, url: str, *, params=None, tries: int = 4, timeout: int = 120):
    """GET with simple exponential backoff. Raises on final failure."""
    last = None
    for attempt in range(tries):
        try:
            r = s.get(url, params=params, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code} from server", response=r)
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            last = e
            wait = 2**attempt
            log(f"  retry {attempt + 1}/{tries} after error: {e} (waiting {wait}s)")
            time.sleep(wait)
    raise RuntimeError(f"Failed after {tries} attempts: {url}") from last


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str) -> None:
    print(f"\nERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)
