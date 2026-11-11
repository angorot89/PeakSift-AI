"""Shorts library release gate: every Short in a creator's library agrees with its own page, its
publishing and its media, against a running PeakSift (read-only).

    SHORTS_ACCEPTANCE_EMAIL=… SHORTS_ACCEPTANCE_PASSWORD=… \\
        python scripts/shorts_acceptance.py --api http://localhost:8000

Signs in as a dedicated acceptance creator (credentials from the environment only) and checks,
for every Short and draft in ``GET /shorts``:

1. **one status**: the Short's page (``GET /shorts/{id}``), Home's recent Shorts and the project's
   summary give the same status; the status matches the publishing state (a Short is
   "published" only when YouTube confirmed it; "on_youtube" never claims it);
2. **honest media**: a rendered Short's file streams (owner-checked, MP4) and a Short that is not
   rendered offers no download; a YouTube link only for a real upload;
3. **versions**: the page lists the Short among its moment's versions, numbered as in the library;
4. **no internals**: no storage keys, task ids, fingerprints, configuration snapshots or tokens;
5. **figures as reported**: performance figures are numbers or null, never invented zeros for a
   Short that is not on YouTube.

Prints each check and exits 1 when any fails. Changes nothing.
"""

import argparse
import os
import sys

import httpx

INTERNAL = ("storage_key", "celery_task_id", "fingerprint", "upload_session", "refresh_token",
            "configuration", "scopes")  # fmt: skip
ON_YOUTUBE = {"on_youtube", "published"}
failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'} {what}")
    if not ok:
        failures.append(what)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    email = os.environ.get("SHORTS_ACCEPTANCE_EMAIL")
    password = os.environ.get("SHORTS_ACCEPTANCE_PASSWORD")
    if not email or not password:
        print("Set SHORTS_ACCEPTANCE_EMAIL and SHORTS_ACCEPTANCE_PASSWORD.", file=sys.stderr)
        return 2
    c = httpx.Client(base_url=args.api, timeout=120)
    if c.post("/auth/login", json={"email": email, "password": password}).status_code != 200:
        print("Sign-in failed.", file=sys.stderr)
        return 2
    library = c.get("/shorts").json()
    shorts = library["shorts"]
    check(bool(shorts), f"the library lists {len(shorts)} Shorts and drafts")
    check(not any(word in str(library) for word in INTERNAL), "the library has no internals")
    home = {s["edit_id"]: s for s in c.get("/workspace/home").json()["recent_shorts"]}
    summaries: dict[str, dict] = {}
    for project_id in {s["project"]["id"] for s in shorts}:
        for s in c.get(f"/projects/{project_id}/summary").json()["shorts"]["recent"]:
            summaries[s["edit_id"]] = s

    for short in shorts:
        name = f"“{short['title']}” ({short['kind']}, {short['status']})"
        page = c.get(f"/shorts/{short['id']}")
        check(page.status_code == 200, f"{name}: its page opens")
        if page.status_code != 200:
            continue
        detail = page.json()
        check(detail["status"] == short["status"], f"{name}: the page says the same status")
        for where, summary in (("Home", home.get(short["id"])),
                               ("the project", summaries.get(short["id"]))):  # fmt: skip
            if summary is not None:
                check(summary["short_status"] == short["status"], f"{name}: {where} agrees")
        publish = short["publish"]["state"]
        if short["status"] == "published":
            check(publish == "published" and short["publish"]["published_at"] is not None,
                  f"{name}: published only with YouTube's confirmation")  # fmt: skip
        if short["status"] == "on_youtube":
            check(publish == "on_youtube" and short["publish"]["published_at"] is None,
                  f"{name}: on YouTube, never called published")  # fmt: skip
        if short["publish"]["video_url"]:
            real = not short["publish"]["simulated"]
            check(real, f"{name}: a YouTube link only for a real upload")
        if short["kind"] == "short":
            numbers = {v["id"]: v["number"] for v in detail["versions"]}
            number = short["version"]["number"]
            check(numbers.get(short["id"]) == number, f"{name}: version {number} of its moment")
        if short["preview"] == "short":
            media = c.get(f"/edits/{short['edit_id']}/content", headers={"Range": "bytes=0-1023"})
            check(media.status_code == 206 and media.headers.get("content-type") == "video/mp4",
                  f"{name}: the rendered Short streams")  # fmt: skip
        elif short["kind"] == "short":
            check(c.get(f"/edits/{short['edit_id']}/download").status_code != 200,
                  f"{name}: nothing to download before it is rendered")  # fmt: skip
        if short["status"] not in ON_YOUTUBE:
            check(short["performance"] is None or short["status"] == "needs_attention",
                  f"{name}: no figures before it is on YouTube")  # fmt: skip
        check(not any(word in str(detail) for word in INTERNAL), f"{name}: no internals")

    print("SHORTS ACCEPTANCE " + ("FAILED" if failures else "PASSED"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
