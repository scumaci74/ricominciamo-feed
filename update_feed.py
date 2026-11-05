#!/usr/bin/env python3
"""Generate a personal podcast RSS from QN's public Ricominciamo pages.

Sources:
- JSON-LD ItemList on the series page supplies episode URLs and dates.
- HTML <article-audio data-url=...> supplies each MP3 URL and duration.

No subscriber credentials or signed URLs are used. Existing episodes are retained.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
import json
import sys
import xml.etree.ElementTree as ET

import requests

SERIES_URL = "https://www.quotidiano.net/podcast/ricominciamo"
FEED_PATH = Path("feed.xml")
PODCAST_TITLE = "Ricominciamo - Mattia Feltri"
COVER_URL = (
    "https://www.quotidiano.net/image-service/view/acePublic/alias/"
    "contentid/YzQ3MGQyMDYtYzQyOC00/2/ricominciamo.webp"
)
ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM = "http://www.w3.org/2005/Atom"
ET.register_namespace("itunes", ITUNES)
ET.register_namespace("atom", ATOM)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RicominciamoPersonalRSS/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ldjson_chunks: list[str] = []
        self._in_ldjson = False
        self._buffer: list[str] = []
        self.audio_attrs: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_ldjson = True
            self._buffer = []
        if tag == "article-audio" and a.get("data-url"):
            self.audio_attrs.append(a)

    def handle_data(self, data: str) -> None:
        if self._in_ldjson:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_ldjson:
            self.ldjson_chunks.append("".join(self._buffer))
            self._buffer = []
            self._in_ldjson = False


def fetch_html(url: str) -> str:
    response = SESSION.get(url, timeout=30)

    print(f"URL richiesto: {url}", flush=True)
    print(f"HTTP status: {response.status_code}", flush=True)
    print(f"URL finale: {response.url}", flush=True)
    print(f"Content-Type: {response.headers.get('content-type')}", flush=True)
    print(f"Dimensione HTML: {len(response.content)} byte", flush=True)
    print(f"JSON-LD presenti: {response.text.count('application/ld+json')}", flush=True)
    print(f"ItemList presenti: {response.text.count('ItemList')}", flush=True)
    print(f"Episodio di prova presente: {'grande-ancora-balnx6w0' in response.text}", flush=True)

    response.raise_for_status()
    return response.text


def ld_objects(node):
    if isinstance(node, list):
        for item in node:
            yield from ld_objects(item)
    elif isinstance(node, dict):
        yield node
        if "@graph" in node:
            yield from ld_objects(node["@graph"])


def types_include(node: dict, requested: str) -> bool:
    kinds = node.get("@type", [])
    return requested in (kinds if isinstance(kinds, list) else [kinds])


def series_episodes(html: str) -> list[dict]:
    parser = PageParser()
    parser.feed(html)
    candidates: list[dict] = []
    for chunk in parser.ldjson_chunks:
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        for obj in ld_objects(data):
            if not types_include(obj, "ItemList"):
                continue
            for entry in obj.get("itemListElement", []):
                episode = entry.get("item", entry) if isinstance(entry, dict) else {}
                if not isinstance(episode, dict):
                    continue
                link = episode.get("url", "")
                if isinstance(link, dict):
                    link = link.get("@id", "")
                if not link or "/podcast/ricominciamo/" not in str(link):
                    continue
                candidates.append({
                    "url": urljoin(SERIES_URL, str(link)).split("#")[0],
                    "title": episode.get("name") or "Senza titolo",
                    "description": episode.get("description") or "",
                    "date": episode.get("datePublished") or "",
                    "image": (episode.get("image") or {}).get("url", "")
                    if isinstance(episode.get("image"), dict)
                    else (episode.get("image") or ""),
                })
    return list({ep["url"]: ep for ep in candidates}.values())


def read_episode_audio(url: str) -> tuple[str, str, str]:
    parser = PageParser()
    parser.feed(fetch_html(url))
    for attrs in parser.audio_attrs:
        audio = attrs.get("data-url", "")
        if urlsplit(audio).hostname == "traffic.megaphone.fm":
            return audio, attrs.get("data-duration", ""), attrs.get("data-artwork", "")
    raise ValueError(f"Non trovo un MP3 Megaphone in {url}")


def parse_date(date: str) -> datetime:
    try:
        return datetime.fromisoformat(date.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, AttributeError):
        try:
            return parsedate_to_datetime(date).astimezone(timezone.utc)
        except (ValueError, TypeError, AttributeError):
            return datetime(1970, 1, 1, tzinfo=timezone.utc)


def read_existing() -> dict[str, dict]:
    if not FEED_PATH.exists():
        return {}
    try:
        root = ET.parse(FEED_PATH).getroot()
    except ET.ParseError as exc:
        raise RuntimeError("Il feed esistente non è XML valido: non lo sovrascrivo") from exc
    result = {}
    for item in root.findall("./channel/item"):
        guid = item.findtext("guid")
        audio = item.find("enclosure")
        if not guid or audio is None or not audio.get("url"):
            continue
        image = item.find(f"{{{ITUNES}}}image")
        result[guid] = {
            "url": guid,
            "title": item.findtext("title", ""),
            "description": item.findtext("description", ""),
            "date": item.findtext("pubDate", ""),
            "audio": audio.get("url"),
            "duration": item.findtext(f"{{{ITUNES}}}duration", ""),
            "image": image.get("href", "") if image is not None else COVER_URL,
            "length": int(audio.get("length") or 0),
        }
    return result


def audio_length(url: str) -> int:
    """Get real audio size without downloading the MP3."""
    try:
        response = SESSION.head(url, timeout=30, allow_redirects=True)
        if response.ok:
            n = int(response.headers.get("Content-Length") or 0)
            if n > 0:
                return n
    except (requests.RequestException, ValueError):
        pass
    try:
        with SESSION.get(
            url, timeout=30, headers={"Range": "bytes=0-0"}, stream=True
        ) as response:
            response.raise_for_status()
            content_range = response.headers.get("Content-Range", "")
            if "/" in content_range:
                n = int(content_range.rsplit("/", 1)[-1])
                if n > 0:
                    return n
            n = int(response.headers.get("Content-Length") or 0)
            if n > 0 and response.status_code == 200:
                return n
    except (requests.RequestException, ValueError):
        pass
    raise ValueError(f"Impossibile determinare la dimensione dell'audio: {url}")


def add(parent: ET.Element, tag: str, value: str | int) -> ET.Element:
    return _add(parent, tag, str(value))


def _add(parent: ET.Element, tag: str, value: str) -> ET.Element:
    child = ET.SubElement(parent, tag)
    child.text = value
    return child


def make_feed(episodes: dict[str, dict]) -> bytes:
    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    add(channel, "title", PODCAST_TITLE)
    add(channel, "link", SERIES_URL)
    add(channel, "description", "Feed personale non ufficiale del podcast Ricominciamo di Mattia Feltri, pubblicato da QN.")
    add(channel, "language", "it-IT")
    add(channel, "lastBuildDate", format_datetime(datetime.now(timezone.utc)))
    add(channel, f"{{{ITUNES}}}author", "Mattia Feltri")
    add(channel, f"{{{ITUNES}}}explicit", "false")
    ET.SubElement(channel, f"{{{ITUNES}}}image", {"href": COVER_URL})
    img = ET.SubElement(channel, "image")
    add(img, "url", COVER_URL)
    add(img, "title", PODCAST_TITLE)
    add(img, "link", SERIES_URL)
    for episode in sorted(episodes.values(), key=lambda e: parse_date(e["date"]), reverse=True)[:200]:
        item = ET.SubElement(channel, "item")
        add(item, "title", episode["title"])
        add(item, "description", episode["description"])
        add(item, "link", episode["url"])
        guid = add(item, "guid", episode["url"])
        guid.set("isPermaLink", "true")
        add(item, "pubDate", format_datetime(parse_date(episode["date"])))
        add(item, f"{{{ITUNES}}}author", "Mattia Feltri")
        if episode.get("duration"):
            add(item, f"{{{ITUNES}}}duration", episode["duration"])
        if episode.get("image"):
            ET.SubElement(item, f"{{{ITUNES}}}image", {"href": episode["image"]})
        ET.SubElement(item, "enclosure", {"url": episode["audio"], "type": "audio/mpeg", "length": str(episode.get("length", 0))})
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def main() -> int:
    existing = read_existing()
    listing = series_episodes(fetch_html(SERIES_URL))
    if not listing:
        raise RuntimeError("Nessun episodio trovato nel JSON-LD ItemList: lascio intatto feed.xml")
    added = 0
    for episode in listing:
        if episode["url"] in existing:
            continue
        try:
            audio, duration, artwork = read_episode_audio(episode["url"])
        except (requests.RequestException, ValueError) as exc:
            print(f"Errore per {episode['url']}: {exc}", file=sys.stderr)
            continue
        try:
            length = audio_length(audio)
        except ValueError as exc:
            print(f"Errore per {episode['url']}: {exc}", file=sys.stderr)
            continue
        existing[episode["url"]] = {
            **episode,
            "audio": audio,
            "duration": duration,
            "length": length,
            "image": episode.get("image") or artwork or COVER_URL,
        }
        added += 1
    if added == 0 and FEED_PATH.exists():
        print(f"Nessun nuovo episodio. Trovati {len(listing)} collegamenti; feed invariato.")
        return 0
    if not existing:
        raise RuntimeError("Nessun episodio valido: feed non generato")
    FEED_PATH.write_bytes(make_feed(existing))
    print(f"Feed aggiornato: {added} nuove puntate, {len(existing)} totali")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (requests.RequestException, RuntimeError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        sys.exit(1)
