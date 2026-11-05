"""Save your own data from WHOOP's official developer API (OAuth 2.0), read-only, before the access runs out.

Credentials stay in a local file you fill in yourself; this script never prints them. You sign in on WHOOP's own page.
Every run writes the untouched JSON to a new <data>/<timestamp>/ folder. Keep that folder out of git.

  <data>/credentials.env, mode 600:
      WHOOP_CLIENT_ID=...
      WHOOP_CLIENT_SECRET=...
      WHOOP_REDIRECT_URI=http://localhost:8765/callback      must match the app's registered redirect URL exactly

  python re/whoop_api_fetch.py <data>

A localhost redirect is caught by this script. With any other redirect, sign in and paste the address the browser lands on into
<data>/redirected_url.txt.
"""
from __future__ import annotations

import collections
import datetime as dt
import http.server
import json
import os
import secrets
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API = "https://api.prod.whoop.com/developer"
# read:profile (name, email) is left out: the research does not need it.
SCOPES = "offline read:recovery read:cycles read:workout read:sleep read:body_measurement"
COLLECTIONS = {"cycles": "/v2/cycle", "recoveries": "/v2/recovery", "sleeps": "/v2/activity/sleep", "workouts": "/v2/activity/workout"}
SINGLES = {"body_measurement": "/v2/user/measurement/body"}
PAGE_LIMIT = 25
MAX_RETRIES = 6
SIGN_IN_SECONDS = 600
USER_AGENT = "wearable5-research/1.0"


class ApiError(RuntimeError):
    pass


def http_call(url: str, headers: dict, data: bytes | None = None) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def read_credentials(path: str) -> dict:
    if stat.S_IMODE(os.stat(path).st_mode) & 0o077:
        os.chmod(path, 0o600)
    values = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"\'')
    missing = [k for k in ("WHOOP_CLIENT_ID", "WHOOP_CLIENT_SECRET", "WHOOP_REDIRECT_URI") if not values.get(k)]
    if missing:
        raise ApiError(f"{path} lacks {', '.join(missing)}")
    return values


def authorize_url(creds: dict, state: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({"response_type": "code", "client_id": creds["WHOOP_CLIENT_ID"],
                                                    "redirect_uri": creds["WHOOP_REDIRECT_URI"], "scope": SCOPES, "state": state})


def code_from_redirect(url: str, state: str) -> str:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url.strip()).query)
    if query.get("state", [""])[0] != state:
        raise ApiError("the sign-in reply has the wrong state; nothing was used")
    if "error" in query:
        raise ApiError(f"WHOOP refused the sign-in: {query['error'][0]}: {query.get('error_description', [''])[0]}")
    if "code" not in query:
        raise ApiError("the sign-in reply has no code")
    return query["code"][0]


def wait_for_redirect(creds: dict, data: str, state: str) -> str:
    target = urllib.parse.urlparse(creds["WHOOP_REDIRECT_URI"])
    if target.hostname in ("localhost", "127.0.0.1"):
        seen = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if urllib.parse.urlparse(self.path).path == target.path:
                    seen["url"] = self.path
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Klaar. Je kunt dit tabblad sluiten.")

            def log_message(self, *_):
                pass

        server = http.server.HTTPServer((target.hostname, target.port or 80), Handler)
        server.timeout = 1
        end = time.time() + SIGN_IN_SECONDS
        while "url" not in seen and time.time() < end:
            server.handle_request()
        server.server_close()
        if "url" not in seen:
            raise ApiError("no sign-in within the time limit")
        return code_from_redirect(seen["url"], state)
    path = os.path.join(data, "redirected_url.txt")
    end = time.time() + SIGN_IN_SECONDS
    while time.time() < end:
        if os.path.exists(path) and os.path.getsize(path):
            url = open(path, encoding="utf-8").read()
            os.remove(path)
            return code_from_redirect(url, state)
        time.sleep(1)
    raise ApiError("no redirected_url.txt within the time limit")


class Client:
    """Bearer calls with retry on 429 and 5xx, and one token refresh on 401."""

    def __init__(self, creds: dict, tokens: dict, save_tokens, call=http_call, sleep=time.sleep):
        self.creds, self.tokens, self.save_tokens, self.call, self.sleep = creds, tokens, save_tokens, call, sleep
        self.requests = 0

    def token_request(self, fields: dict) -> dict:
        body = urllib.parse.urlencode({**fields, "client_id": self.creds["WHOOP_CLIENT_ID"],
                                       "client_secret": self.creds["WHOOP_CLIENT_SECRET"]}).encode()
        status, _, raw = self.call(TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, body)
        if status != 200:
            raise ApiError(f"token request failed with HTTP {status}")  # the reply may echo credentials, so it is not shown
        return json.loads(raw)

    def exchange(self, code: str) -> None:
        self.tokens = self.token_request({"grant_type": "authorization_code", "code": code,
                                          "redirect_uri": self.creds["WHOOP_REDIRECT_URI"]})
        self.save_tokens(self.tokens)

    def refresh(self) -> None:
        if not self.tokens.get("refresh_token"):
            raise ApiError("the access token expired and there is no refresh token; sign in again")
        self.tokens = self.token_request({"grant_type": "refresh_token", "refresh_token": self.tokens["refresh_token"],
                                          "scope": "offline"})
        self.save_tokens(self.tokens)

    def get(self, path: str, query: dict | None = None):
        url = API + path + ("?" + urllib.parse.urlencode(query) if query else "")
        refreshed = False
        for attempt in range(MAX_RETRIES):
            self.requests += 1
            status, headers, raw = self.call(url, {"Authorization": "Bearer " + self.tokens["access_token"]})
            if status == 200:
                return json.loads(raw)
            if status == 401 and not refreshed:
                refreshed = True
                self.refresh()
            elif status == 429 or status >= 500:
                lowered = {k.lower(): v for k, v in headers.items()}
                wait = lowered.get("retry-after") or lowered.get("x-ratelimit-reset") or 2 ** attempt
                self.sleep(min(float(wait), 120))
            else:
                raise ApiError(f"GET {path} failed with HTTP {status}")
        raise ApiError(f"GET {path} kept failing")

    def all_records(self, path: str) -> list[dict]:
        records, token = [], None
        while True:
            query = {"limit": PAGE_LIMIT, **({"nextToken": token} if token else {})}
            page = self.get(path, query)
            records.extend(page.get("records", []))
            token = page.get("next_token")
            if not token:
                return records


def summary(name: str, records: list[dict]) -> str:
    states = collections.Counter(r.get("score_state", "?") for r in records)
    starts = sorted(r.get("start") or r.get("created_at") or "" for r in records)
    return f"{name}: {len(records)} records, {starts[0][:10] if starts else '-'} to {starts[-1][:10] if starts else '-'}, {dict(states)}"


def write_private(path: str, value) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=1, sort_keys=True)


def save_everything(client: Client, data: str) -> str:
    out = os.path.join(data, dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out, mode=0o700)
    errors = []
    for name, path in COLLECTIONS.items():
        try:
            records = client.all_records(path)
            write_private(os.path.join(out, f"{name}.json"), records)
            print(summary(name, records), flush=True)
        except ApiError as e:
            errors.append(str(e))
            print("FAILED", name, e, flush=True)
    for name, path in SINGLES.items():
        try:
            write_private(os.path.join(out, f"{name}.json"), client.get(path))
            print(f"{name}: saved", flush=True)
        except ApiError as e:
            errors.append(str(e))
            print("FAILED", name, e, flush=True)
    write_private(os.path.join(out, "manifest.json"), {"fetched_at": dt.datetime.now().astimezone().isoformat(), "api": API,
                                                        "requests": client.requests, "errors": errors})
    print(f"{client.requests} requests; saved to {out}", flush=True)
    return out


def main() -> int:
    data = sys.argv[1]
    creds = read_credentials(os.path.join(data, "credentials.env"))
    token_path = os.path.join(data, "tokens.json")
    tokens = json.load(open(token_path)) if os.path.exists(token_path) else {}
    client = Client(creds, tokens, lambda t: write_private(token_path, t))
    if not tokens:
        state = secrets.token_urlsafe(16)
        subprocess.run(["open", authorize_url(creds, state)], check=True)
        print("sign in on the WHOOP page that just opened", flush=True)
        client.exchange(wait_for_redirect(creds, data, state))
        print("signed in", flush=True)
    save_everything(client, data)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ApiError as e:
        print("stopped:", e)
        sys.exit(2)
