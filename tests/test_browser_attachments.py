import base64
import io
import zipfile

import pytest

from shipit_agent.browser_attachments import decode_uploads


def upload(name, data, mime="application/octet-stream"):
    return {"name": name, "mime": mime, "data": base64.b64encode(data).decode()}


def zipped(path, xml):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(path, xml)
    return stream.getvalue()


@pytest.mark.parametrize(
    "name,path,xml,expected",
    [
        (
            "memo.docx",
            "word/document.xml",
            '<w:document xmlns:w="word"><w:p><w:r><w:t>Project memo</w:t></w:r></w:p></w:document>',
            "Project memo",
        ),
        (
            "deck.pptx",
            "ppt/slides/slide1.xml",
            '<p:sld xmlns:p="presentation" xmlns:a="drawing"><a:t>Quarterly review</a:t></p:sld>',
            "Slide 1\nQuarterly review",
        ),
        (
            "cells.xlsx",
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="sheet"><row><c r="A1" t="inlineStr"><is><t>Revenue</t></is></c><c r="B1"><f>SUM(B2:B3)</f><v>12</v></c></row></worksheet>',
            "SUM(B2:B3)",
        ),
    ],
)
def test_real_office_archives_are_read_in_memory(name, path, xml, expected):
    images, docs = decode_uploads([upload(name, zipped(path, xml))])
    assert not images and expected in docs[0]["text"]


def test_text_budget_is_disclosed():
    _, docs = decode_uploads([upload("notes.txt", b"evidence " * 10000)])
    assert docs[0]["truncated"] is True
    assert len(docs[0]["text"]) == 60000


def test_images_stay_as_data_urls():
    images, docs = decode_uploads(
        [upload("image.png", b"\x89PNG\r\n\x1a\nfixture", "image/png")]
    )
    assert images[0].startswith("data:image/png;base64,") and docs == []


@pytest.mark.parametrize(
    "item",
    [
        {"name": "bad.txt", "data": "%%%"},
        upload("fake.png", b"not an image", "image/png"),
        upload("binary.txt", b"secret\x00data"),
        upload("unsupported.exe", b"payload"),
        upload("broken.docx", b"not a zip"),
    ],
)
def test_invalid_files_do_not_reach_model(item):
    with pytest.raises(ValueError):
        decode_uploads([item])


def test_zip_expansion_is_bounded():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"a" * (33 * 1024 * 1024))
    with pytest.raises(ValueError, match="expands"):
        decode_uploads([upload("large.docx", stream.getvalue())])
