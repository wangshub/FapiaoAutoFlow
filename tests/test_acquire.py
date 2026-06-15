"""acquire 来源提取的单元测试(用假下载器/假二维码解码器)。"""

from fapiao.acquire import acquire_sources
from fapiao.models import (
    SOURCE_IMAGE,
    SOURCE_PDF,
    SOURCE_TEXT,
    Attachment,
    EmailMessage,
)

PDF_BYTES = b"%PDF-1.4 fake pdf body"


def _no_download(url):
    return None


def _no_qr(data):
    return []


def test_pdf_attachment_takes_priority():
    em = EmailMessage(uid=1, subject="发票", sender="a@b.com", date="",
                      body_text="见附件 http://x.com/inv.pdf",
                      attachments=[Attachment("发票.pdf", "application/pdf", PDF_BYTES)])
    res = acquire_sources(em, _no_download, _no_qr)
    assert len(res.sources) == 1
    assert res.sources[0].kind == SOURCE_PDF
    assert res.sources[0].data == PDF_BYTES
    # 有附件就不再去碰链接
    assert res.pending_reasons == []


def test_image_attachment_classified():
    em = EmailMessage(uid=2, subject="", sender="", date="",
                      attachments=[Attachment("票.jpg", "image/jpeg", b"\xff\xd8jpg")])
    res = acquire_sources(em, _no_download, _no_qr)
    assert res.sources[0].kind == SOURCE_IMAGE


def test_body_link_downloaded_as_pdf():
    def downloader(url):
        return (PDF_BYTES, "application/pdf")

    em = EmailMessage(uid=3, subject="", sender="", date="",
                      body_text="请下载 https://files.example.com/a.pdf 谢谢")
    res = acquire_sources(em, downloader, _no_qr)
    assert len(res.sources) == 1
    assert res.sources[0].kind == SOURCE_PDF
    assert res.sources[0].origin == "正文链接"


def test_link_to_html_login_goes_pending():
    def downloader(url):
        return (b"<!DOCTYPE html><html>login</html>", "text/html")

    em = EmailMessage(uid=4, subject="", sender="", date="",
                      body_text="登录后下载 https://platform.example.com/view?id=9")
    res = acquire_sources(em, downloader, _no_qr)
    assert res.sources == []
    assert any("网页" in r for r in res.pending_reasons)


def test_qr_code_link_downloaded():
    def downloader(url):
        return (PDF_BYTES, "application/pdf")

    def qr(data):
        return ["https://files.example.com/from_qr.pdf"]

    em = EmailMessage(uid=5, subject="", sender="", date="",
                      inline_images=[Attachment("q.png", "image/png", b"img")])
    res = acquire_sources(em, downloader, qr)
    assert len(res.sources) == 1
    assert res.sources[0].origin == "二维码链接"


def test_body_text_with_keywords():
    em = EmailMessage(uid=6, subject="", sender="", date="",
                      body_text="发票号码 123 价税合计 100元 税额 6元")
    res = acquire_sources(em, _no_download, _no_qr)
    assert len(res.sources) == 1
    assert res.sources[0].kind == SOURCE_TEXT
    assert "价税合计" in res.sources[0].text


def test_nothing_found_is_pending():
    em = EmailMessage(uid=7, subject="hi", sender="", date="", body_text="周末愉快")
    res = acquire_sources(em, _no_download, _no_qr)
    assert res.sources == []
    assert res.pending_reasons


def test_zip_attachment_recurses():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("发票.pdf", PDF_BYTES)
        zf.writestr("readme.txt", b"ignore me")
    em = EmailMessage(uid=8, subject="", sender="", date="",
                      attachments=[Attachment("发票.zip", "application/zip", buf.getvalue())])
    res = acquire_sources(em, _no_download, _no_qr)
    assert len(res.sources) == 1
    assert res.sources[0].kind == SOURCE_PDF
