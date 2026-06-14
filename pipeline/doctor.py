"""Pre-flight checks: run before the first full pipeline ('make doctor')."""

import shutil

from pipeline import config as C
from pipeline.util import log, session


def check(label: str, ok: bool, hint: str = "") -> bool:
    mark = "OK " if ok else "FAIL"
    log(f"[{mark}] {label}" + (f" — {hint}" if (not ok and hint) else ""))
    return ok


def main() -> None:
    s = session()
    all_ok = True

    all_ok &= check(
        "LINZ_API_KEY set",
        bool(C.LINZ_API_KEY),
        "copy .env.example to .env and paste your key",
    )

    if C.LINZ_API_KEY:
        try:
            r = s.get(
                C.LINZ_WFS_URL.format(key=C.LINZ_API_KEY),
                params={"service": "WFS", "request": "GetCapabilities"},
                timeout=30,
            )
            all_ok &= check("LINZ WFS reachable + key accepted", r.status_code == 200,
                            f"HTTP {r.status_code}")
        except Exception as e:
            all_ok &= check("LINZ WFS reachable", False, str(e))

    try:
        r = s.get(C.ELEVATION_STAC_ROOT, timeout=30)
        all_ok &= check("nz-elevation STAC reachable", r.status_code == 200,
                        f"HTTP {r.status_code}")
    except Exception as e:
        all_ok &= check("nz-elevation STAC reachable", False, str(e))

    try:
        r = s.get(C.AC_HUB_SEARCH, params={"q": "flood", "limit": 1}, timeout=30)
        all_ok &= check("Auckland Council Hub API reachable", r.status_code == 200,
                        f"HTTP {r.status_code} — may need URL pinning, see config.py")
    except Exception as e:
        all_ok &= check("Auckland Council Hub API reachable", False, str(e))

    all_ok &= check("tippecanoe on PATH", shutil.which("tippecanoe") is not None,
                    "see README one-time setup")

    # Earth Engine is only needed for the optional 'make change' stage, so a
    # failure here is a soft warning — it does not flip all_ok. The check is
    # twofold: the library imports, and ee.Initialize() finds credentials.
    ee_hint = ("only needed for 'make change' — install earthengine-api and run "
               "'earthengine authenticate' (free non-commercial tier)")
    try:
        import ee  # noqa: PLC0415
        try:
            ee.Initialize()
            check("Earth Engine authenticated", True)
        except Exception as e:
            check("Earth Engine authenticated", False,
                  f"{ee_hint}; init error: {e}")
    except Exception:
        check("Earth Engine library installed", False, ee_hint)

    log("\nAll checks passed — run 'make all'." if all_ok
        else "\nFix the FAIL items above, then re-run 'make doctor'. "
             "(Earth Engine is optional unless you're running 'make change'.)")


if __name__ == "__main__":
    main()
