"""Static website contracts complement the desktop/mobile browser checks."""

from html.parser import HTMLParser
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from rde.interface.mcp.contracts import CONTRACTS

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_homepage_local_assets_and_anchors_exist():
    page = Page((DOCS / "index.html").read_text(encoding="utf-8"))
    ids = {attrs["id"] for _, attrs in page.tags if "id" in attrs}
    assert {"workflow", "clinical", "autoresearch", "install"} <= ids
    for tag, attrs in page.tags:
        for attr in ("src", "href"):
            target = attrs.get(attr, "")
            if target.startswith("#"):
                assert target[1:] in ids
            elif target and not target.startswith(("https:", "http:")):
                assert (DOCS / target.split("#")[0]).is_file(), target
        if tag == "img":
            assert attrs.get("alt") and attrs.get("width") and attrs.get("height")
    assert sum(tag == "h1" for tag, _ in page.tags) == 1
    assert sum(tag == "tr" and "data-category" in attrs for tag, attrs in page.tags) == 7


def test_guide_inventory_covers_every_registered_tool():
    guide = (DOCS / "guide.html").read_text(encoding="utf-8")
    inventory = guide.split("const verifiedTools = [", 1)[1].split("];", 1)[0]
    for tool in CONTRACTS:
        assert re.search(rf"\b{tool}\b", inventory), tool
    assert "lists 49 expected" not in guide
    assert 'href="index.html"' in guide


def test_all_new_diagrams_have_accessible_titles():
    for name in (
        "architecture.svg",
        "architecture-zh.svg",
        "autoresearch.svg",
        "evidence-chain.svg",
    ):
        root = ET.fromstring((DOCS / "assets" / name).read_text(encoding="utf-8"))
        assert root.get("viewBox")
        assert root.find("{http://www.w3.org/2000/svg}title") is not None
        assert root.find("{http://www.w3.org/2000/svg}desc") is not None
