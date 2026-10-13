from pathlib import Path

import pytest

from deerflow.utils.text_detection import _is_active_content_mime_type


@pytest.mark.parametrize("name", ["page.xhtml", "page.XHTML", "icon.svg", "feed.xml", "feed.rss", "page.html"])
@pytest.mark.parametrize("mime", [None, "text/plain"])
def test_active_filename_is_attached_without_system_mime_mapping(name, mime):
    assert _is_active_content_mime_type(mime, Path(name))


def test_passive_files_remain_inline_and_xml_mime_is_still_active():
    assert not _is_active_content_mime_type("text/plain", "notes.txt")
    assert _is_active_content_mime_type("application/custom+xml", "unknown.data")
