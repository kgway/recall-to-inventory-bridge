# SPDX-License-Identifier: MPL-2.0
"""CPSC-only source adapter. Original API records remain attached to evidence."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from .engine import now

API = "https://www.saferproducts.gov/RestWebServices/Recall"
CURATED_IDS = (11038, 9996, 10311)


def normalize_cpsc(record, source_url, acquired_at=None):
    if not isinstance(record, dict) or type(record.get("RecallID")) is not int:
        raise ValueError("Invalid CPSC recall record.")
    url = record.get("URL", "")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"cpsc.gov", "www.cpsc.gov"} or not parsed.path.startswith("/Recalls/"):
        raise ValueError("CPSC detail URL is outside the official source boundary.")
    original = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(original.encode()).hexdigest()
    parts = [record.get("Title", ""), record.get("Description", "")]
    for field in ("Products", "Hazards", "Remedies"):
        parts.extend(item.get("Name", "") for item in record.get(field, []) if isinstance(item, dict))
    text = "\n\n".join(part for part in parts if part)
    target_component = "power_adapter" if "power adapters" in (record["Title"] + " " + " ".join(p.get("Name", "") for p in record.get("Products", []))).lower() else None
    return {"notice_id": "US-CPSC:" + str(record["RecallID"]), "agency": "US-CPSC", "jurisdiction": "US", "target_component": target_component,
            "source_id": str(record["RecallID"]), "recall_number": str(record.get("RecallNumber", "")),
            "title": record["Title"], "url": url, "last_publish_date": record.get("LastPublishDate"),
            "acquired_at": acquired_at or now(), "raw_api": record, "source_conflict": False,
            "snapshots": [{"id": "api:" + str(record["RecallID"]) + ":" + sha[:16], "kind": "cpsc-api",
                           "sha256": sha, "url": source_url, "text": text}]}


class RecallPageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.started = False
        self.stopped = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "footer", "header"}:
            self.skip += 1
        if tag == "h1":
            self.started = True
        if tag in {"p", "div", "h1", "h2", "h3", "li", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "footer", "header"}:
            self.skip = max(0, self.skip - 1)
        if tag in {"p", "div", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, text):
        if text.strip() == "Related Recalls":
            self.stopped = True
        if self.started and not self.stopped and not self.skip:
            self.parts.append(text)

    def text(self):
        lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in "".join(self.parts).split("\n")]
        return "\n".join(line for line in lines if line)


class OfficialRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, new_url):
        validate_url(new_url)
        return super().redirect_request(request, fp, code, msg, headers, new_url)


def validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Only official HTTPS source URLs are allowed.")
    if parsed.hostname == "www.saferproducts.gov" and parsed.path == "/RestWebServices/Recall":
        return
    if parsed.hostname in {"cpsc.gov", "www.cpsc.gov"} and parsed.path.startswith("/Recalls/"):
        return
    raise ValueError("URL is outside the CPSC source allowlist.")


def fetch(url, max_bytes=1_000_000):
    validate_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "RecallToInventoryBridge/0.1 (contest demo)", "Accept": "application/json,text/html"})
    opener = urllib.request.build_opener(OfficialRedirectHandler())
    with opener.open(request, timeout=25) as response:
        validate_url(response.geturl())
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("Source response exceeded its size limit.")
    return raw


def fetch_notice(recall_id):
    if type(recall_id) is not int or recall_id <= 0:
        raise ValueError("Invalid CPSC ID.")
    url = API + "?" + urllib.parse.urlencode({"format": "json", "RecallID": recall_id})
    records = json.loads(fetch(url))
    if not isinstance(records, list) or len(records) != 1 or records[0].get("RecallID") != recall_id:
        raise ValueError("CPSC ID query returned unexpected records.")
    note = normalize_cpsc(records[0], url)
    try:
        raw = fetch(note["url"])
        parser = RecallPageText()
        parser.feed(raw.decode("utf-8"))
        text = parser.text()
        if len(text) < 200:
            raise ValueError("Official detail text could not be extracted.")
        raw_sha = hashlib.sha256(raw).hexdigest()
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        # The content hash excludes fetch time; unchanged content is reusable.
        note["snapshots"].append({"id": "page:" + str(recall_id) + ":" + sha[:16], "kind": "cpsc-detail",
                                 "url": note["url"], "sha256": sha, "raw_html_sha256": raw_sha, "text": text[:60_000]})
        # Conservative detection of additional restrictive language. The agent
        # must ask for review rather than resolve a source discrepancy itself.
        api_text = note["snapshots"][0]["text"].lower()
        for qualifier in ("date code", "not affected", "qualifying serial"):
            if qualifier in text.lower() and qualifier not in api_text:
                note["source_conflict"] = True
    except (OSError, ValueError) as exc:
        note["detail_status"] = "UNAVAILABLE"
        note["detail_error"] = type(exc).__name__
        # API-only evidence is explicitly marked. Missing page data must not
        # silently remove a known qualification or permit release.
        note["source_conflict"] = True
    return note


def fetch_curated():
    return [fetch_notice(recall_id) for recall_id in CURATED_IDS]
