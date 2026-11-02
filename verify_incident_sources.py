#!/usr/bin/env python3
"""Re-fetch public incident citations and check their named sections. No actions."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import re
from urllib.request import Request, urlopen
from incident_eval import DATA, SOURCES, load_cases


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skipping += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skipping -= 1

    def handle_data(self, text):
        if not self.skipping:
            self.parts.append(text)


def normalized(text):
    return re.sub(r'\s+', ' ', text).strip().casefold()


def check(source, cases):
    with urlopen(Request(source['url'], headers={'User-Agent': 'public-incident-eval/1.0'}), timeout=45) as response:
        raw = response.read()
        if response.status != 200:
            raise ValueError(f"{source['key']}: HTTP {response.status}")
        resolved = response.url
    parser = PageText()
    parser.feed(raw.decode('utf-8'))
    text = normalized(' '.join(parser.parts))
    for case in cases:
        if normalized(case['source_section']) not in text:
            raise ValueError(f"{case['id']}: source section missing; manual review required")
    return dict(key=source['key'], url=source['url'], final_url=resolved, status=200,
                sha256=hashlib.sha256(raw).hexdigest(),
                verified_at=datetime.now(timezone.utc).isoformat(),
                method='HTTP GET; named section present; symptoms and labels manually reviewed on 2026-11-01 Pacific')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='replace fetch receipts after review')
    args = parser.parse_args()
    cases = load_cases(DATA, SOURCES)
    sources = json.loads(SOURCES.read_text())
    def run(source):
        return check(source, [c for c in cases if c['source_key'] == source['key']])
    with ThreadPoolExecutor(max_workers=6) as pool:
        receipts = list(pool.map(run, sources))
    if args.write:
        SOURCES.write_text(json.dumps(receipts, indent=2) + '\n')
    print(f'{len(receipts)} unique pages returned HTTP 200; {len(cases)} incident sections found.')
    print('Section matching does not replace a human reading the page and checking each claim.')


if __name__ == '__main__':
    main()
