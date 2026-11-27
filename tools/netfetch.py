#!/usr/bin/env python3
"""Polite HTTP helpers shared by tools/refs_fetch.py and tools/assets.py (standard library only).

- One request at a time with a minimum interval between requests (rate limit).
- 429 / 5xx / connection errors: retry with exponential backoff; a Retry-After header (seconds or HTTP date) wins.
  A Retry-After longer than max_wait is not cut short: the request fails (FetchError) and says when to run again.
- A connection cut while reading the body (IncompleteRead, reset, timeout) is a FetchError, never a traceback; a
  download keeps its .part and the next run resumes it.
- download(): writes <file>.part, resumes it with an HTTP Range request, checks size and md5 when known, renames to
  the final name only when every check passed, and never overwrites a finished file.
- A generic User-Agent without personal data (no name, no e-mail).

Nothing here reads keys or cookies. The tests run it against a local fake server (tests/test_refs_fetch.py,
tests/test_assets.py); it never needs the real network to be tested.
"""
import email.utils, hashlib, http.client, json, os, sys, time, urllib.error, urllib.request

USER_AGENT = "film-lab-fetch/1.0 (python-urllib; reference and CC0 asset fetcher)"
RETRY_STATUS = {429, 500, 502, 503, 504}
READ_ERRORS = (http.client.HTTPException, ConnectionError, TimeoutError)
CHUNK = 1 << 16


class FetchError(Exception):
    """A request that failed for good (after the retries, or a status that is not retried)."""

    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


def retry_after(value, now=None):
    """Seconds to wait from a Retry-After header value (delta seconds or an HTTP date); None when unreadable."""
    if value is None:
        return None
    value = str(value).strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    now = time.time() if now is None else now
    return max(0.0, when.timestamp() - now)


def utf8_stdio():
    """A Windows console or pipe (cp1252) must not crash on a Vietnamese note or an author's name."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


class Client:
    """Rate-limited, retrying HTTP GET. sleep/clock are injectable so tests do not wait."""

    def __init__(self, min_interval=1.0, retries=5, backoff=2.0, max_wait=120.0, timeout=60,
                 user_agent=USER_AGENT, sleep=None, clock=None, log=None):
        self.min_interval, self.retries, self.backoff = min_interval, retries, backoff
        self.max_wait, self.timeout, self.user_agent = max_wait, timeout, user_agent
        self.sleep, self.clock, self.log = sleep or time.sleep, clock or time.monotonic, log
        self._last = None
        self.requests = 0                      # requests sent (tests and reports)
        self.waited = 0.0                      # seconds slept for backoff

    def _say(self, msg):
        if self.log:
            self.log(msg)

    def _throttle(self):
        if self._last is not None and self.min_interval > 0:
            gap = self.clock() - self._last
            if gap < self.min_interval:
                self.sleep(self.min_interval - gap)
        self._last = self.clock()

    def open(self, url, headers=None):
        """urlopen with the rate limit and retries. -> the open response (use it in a with block)."""
        hdrs = {"User-Agent": self.user_agent}
        hdrs.update(headers or {})
        attempt = 0
        while True:
            self._throttle()
            self.requests += 1
            try:
                return urllib.request.urlopen(urllib.request.Request(url, headers=hdrs), timeout=self.timeout)
            except urllib.error.HTTPError as e:
                status, after = e.code, retry_after(e.headers.get("Retry-After") if e.headers else None)
                e.close()
                if status not in RETRY_STATUS:
                    raise FetchError(f"HTTP {status} for {url}", status) from None
                why = f"HTTP {status}"
            except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as e:
                status, after = None, None
                why = f"{type(e).__name__}: {getattr(e, 'reason', e)}"
            if attempt >= self.retries:
                raise FetchError(f"{why} for {url}: gave up after {attempt + 1} tries", status)
            if after is not None and after > self.max_wait:
                raise FetchError(f"{why} for {url}: the server asks to wait {after:.0f} s "
                                 f"(more than {self.max_wait:.0f} s); run again later", status)
            wait = after if after is not None else self.backoff * (2 ** attempt)
            wait = min(max(wait, 0.0), self.max_wait)
            self._say(f"  {why}, waiting {wait:.0f} s (try {attempt + 2}/{self.retries + 1})")
            self.waited += wait
            self.sleep(wait)
            attempt += 1

    def get(self, url, headers=None):
        with self.open(url, headers) as r:
            try:
                return r.read()
            except READ_ERRORS as e:
                raise FetchError(f"connection cut while reading {url} ({type(e).__name__}): run again") from None

    def get_json(self, url):
        data = self.get(url, {"Accept": "application/json"})
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise FetchError(f"not JSON from {url}: {e}") from None

    def download(self, url, dest, size=None, md5=None):
        """Download url to dest through dest + '.part' (resumed with Range when it exists).
        -> {"status": "exists"|"done", "bytes": n, "resumed": n_already_there}.
        Raises FetchError on a size or md5 mismatch; the .part file is kept so it can be looked at (delete it to
        start over)."""
        if os.path.exists(dest):
            return {"status": "exists", "bytes": os.path.getsize(dest), "resumed": 0}
        try:                                   # an API may give the size as a string
            size = int(size) if size not in (None, "") else None
        except (TypeError, ValueError):
            size = None
        part = dest + ".part"
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        have = os.path.getsize(part) if os.path.exists(part) else 0
        resumed = have
        if not (size is not None and have >= size):
            headers = {"Range": f"bytes={have}-"} if have else {}
            try:
                r = self.open(url, headers)
            except FetchError as e:
                if not (have and size is None and e.status == 416):
                    raise
                r = None                       # size unknown, .part already complete: nothing left to send
            if r is not None:
                with r:
                    status = getattr(r, "status", None) or r.getcode()
                    if have and status != 206:     # the server ignored the Range: start over
                        have, resumed = 0, 0
                    with open(part, "ab" if have else "wb") as f:
                        try:
                            for block in iter(lambda: r.read(CHUNK), b""):
                                f.write(block)
                        except READ_ERRORS as e:
                            raise FetchError(f"connection cut while downloading {os.path.basename(dest)} "
                                             f"({type(e).__name__}); kept {part}, run again to resume") from None
        got = os.path.getsize(part)
        if size is not None and got != size:
            raise FetchError(f"size mismatch for {os.path.basename(dest)}: {got} bytes, expected {size}; "
                             f"kept {part}")
        if md5:
            real = md5_file(part)
            if real.lower() != str(md5).lower():
                raise FetchError(f"md5 mismatch for {os.path.basename(dest)}: {real}, expected {md5}; kept {part} "
                                 "(delete it and run again)")
        os.replace(part, dest)
        return {"status": "done", "bytes": got, "resumed": resumed}
