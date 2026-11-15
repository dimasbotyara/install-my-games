"""Smoke tests for the standalone GitHub Pages documentation."""
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / 'docs'


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.links = []
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'a' and attrs.get('href', '').startswith('#'):
            self.links.append(attrs['href'][1:])
        if tag == 'script' and attrs.get('src'):
            self.assets.append(attrs['src'])
        if tag == 'link' and attrs.get('rel') in ('stylesheet', 'icon'):
            self.assets.append(attrs['href'])


class DocumentationSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (DOCS / 'index.html').read_text(encoding='utf-8')
        cls.page = PageParser()
        cls.page.feed(cls.html)

    def test_navigation_anchors_exist_and_are_unique(self):
        self.assertFalse(set(self.page.links) - set(self.page.ids))
        self.assertFalse([key for key, n in Counter(self.page.ids).items() if n > 1])

    def test_static_assets_are_relative_and_exist(self):
        self.assertTrue(self.page.assets)
        for asset in self.page.assets:
            self.assertFalse(asset.startswith(('/', 'http:','https:')))
            self.assertTrue((DOCS / asset).is_file(), asset)

    def test_essential_guides_and_safe_download_are_present(self):
        for section in ('install', 'usb', 'offline', 'launcher', 'troubleshooting', 'cleanup'):
            self.assertIn(section, self.page.ids)
        self.assertIn('git clone https://github.com/dimasbotyara/install-my-games.git', self.html)
        self.assertIn('curl -fL -o launch.py', self.html)
        self.assertIn('curl -fL -o prepare_usb.py', self.html)
        self.assertNotIn('| bash', self.html)
        self.assertNotIn('| sh', self.html)

    def test_pages_workflow_uploads_docs(self):
        workflow = (ROOT / '.github/workflows/pages.yml').read_text(encoding='utf-8')
        self.assertIn('actions/upload-pages-artifact@v3', workflow)
        self.assertIn('actions/deploy-pages@v4', workflow)
        self.assertIn('path: docs', workflow)


if __name__ == '__main__':
    unittest.main()
