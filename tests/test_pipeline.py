"""集成测试:整条 pipeline(用假下载器/二维码/AI),覆盖去重、待处理、归档。"""

import pytest

from fapiao.config import Config
from fapiao.models import (
    STATUS_OK,
    Attachment,
    EmailMessage,
    InvoiceRecord,
    NormalizedInput,
)
from fapiao.pipeline import Stats, _target_folder, process_email
from fapiao.store import Store

fitz = pytest.importorskip("fitz")


def _text_pdf() -> bytes:
    """造一个带 ASCII 文字层的真实 PDF(fitz 默认字体不能嵌入中文)。"""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "Electronic invoice No 24317000000123 Total 100.00 Tax 5.66 Seller ABC Restaurant",
    )
    data = doc.tobytes()
    doc.close()
    return data


PDF = _text_pdf()


def _config():
    return Config(imap_host="", imap_port=993, imap_user="", imap_password="", min_confidence=0.6)


def _store(tmp_path):
    return Store(tmp_path / "db.sqlite", tmp_path / "archive")


def _fake_extract(number="INV100", confidence=0.95):
    def extract_fn(normalized: NormalizedInput, config, uid=0):
        return InvoiceRecord(发票号码=number, 开票日期="2026-06-01", 价税合计=100.0,
                             confidence=confidence, source_email_uid=uid,
                             source_origin=normalized.source.origin if normalized.source else "",
                             status=STATUS_OK, raw_json="{}")
    return extract_fn


def _no_dl(url):
    return None


def _no_qr(data):
    return []


def test_pdf_attachment_full_flow(tmp_path):
    s = _store(tmp_path)
    em = EmailMessage(uid=1, subject="发票", sender="a@b.com", date="",
                      attachments=[Attachment("发票.pdf", "application/pdf", PDF)])
    stats = process_email(em, s, _config(), _no_dl, _no_qr, extract_fn=_fake_extract())
    assert stats.invoices_saved == 1
    assert stats.pending == 0
    rows = s.all_invoices()
    assert rows[0]["发票号码"] == "INV100"
    # 原始文件已归档
    assert rows[0]["archive_path"].endswith("INV100.pdf")
    s.close()


def test_duplicate_invoice_not_saved_twice(tmp_path):
    s = _store(tmp_path)
    cfg = _config()
    em = EmailMessage(uid=1, subject="", sender="", date="",
                      attachments=[Attachment("a.pdf", "application/pdf", PDF)])
    process_email(em, s, cfg, _no_dl, _no_qr, extract_fn=_fake_extract("DUP1"))
    # 第二封同号发票
    em2 = EmailMessage(uid=2, subject="", sender="", date="",
                       attachments=[Attachment("b.pdf", "application/pdf", PDF)])
    stats = process_email(em2, s, cfg, _no_dl, _no_qr, extract_fn=_fake_extract("DUP1"))
    assert stats.invoices_saved == 0
    assert stats.duplicates == 1
    assert len(s.all_invoices()) == 1
    s.close()


def test_low_confidence_goes_pending(tmp_path):
    s = _store(tmp_path)
    em = EmailMessage(uid=1, subject="", sender="", date="",
                      attachments=[Attachment("a.pdf", "application/pdf", PDF)])
    stats = process_email(em, s, _config(), _no_dl, _no_qr,
                          extract_fn=_fake_extract("LOW1", confidence=0.3))
    assert stats.invoices_saved == 0
    assert stats.pending == 1
    assert len(s.all_invoices()) == 0
    assert len(s.all_pending()) == 1
    s.close()


def test_login_link_goes_pending(tmp_path):
    s = _store(tmp_path)

    def dl(url):
        return (b"<!DOCTYPE html><html>login</html>", "text/html")

    em = EmailMessage(uid=1, subject="发票", sender="a@b.com", date="",
                      body_text="登录下载 https://platform.example.com/v?id=1")
    stats = process_email(em, s, _config(), dl, _no_qr, extract_fn=_fake_extract())
    assert stats.invoices_saved == 0
    assert stats.pending == 1
    assert len(s.all_pending()) == 1
    s.close()


def test_no_source_goes_pending(tmp_path):
    s = _store(tmp_path)
    em = EmailMessage(uid=1, subject="周报", sender="a@b.com", date="", body_text="本周工作")
    stats = process_email(em, s, _config(), _no_dl, _no_qr, extract_fn=_fake_extract())
    assert stats.pending == 1
    s.close()


# ---- 文件夹归类:目标文件夹判定 ----

def test_target_folder_no_source_not_moved():
    cfg = _config()
    assert _target_folder(Stats(emails=1, sources=0, pending=1), cfg) is None


def test_target_folder_saved_goes_done():
    cfg = _config()
    assert _target_folder(Stats(emails=1, sources=1, invoices_saved=1), cfg) == cfg.folder_done


def test_target_folder_duplicate_goes_done():
    cfg = _config()
    assert _target_folder(Stats(emails=1, sources=1, duplicates=1), cfg) == cfg.folder_done


def test_target_folder_strong_source_no_invoice_goes_pending():
    cfg = _config()
    assert _target_folder(
        Stats(emails=1, sources=1, strong_sources=1, pending=1), cfg) == cfg.folder_pending


def test_target_folder_weak_source_only_not_moved():
    # 只有正文链接/二维码下载的来源(strong=0)且没识别出发票 -> 不移动(避免营销邮件误入)
    cfg = _config()
    assert _target_folder(Stats(emails=1, sources=1, strong_sources=0, pending=1), cfg) is None


def test_target_folder_disabled_returns_none():
    cfg = _config()
    cfg.organize_folders = False
    assert _target_folder(Stats(emails=1, sources=1, invoices_saved=1), cfg) is None


def test_process_email_counts_sources(tmp_path):
    s = _store(tmp_path)
    em = EmailMessage(uid=1, subject="发票", sender="a@b.com", date="",
                      attachments=[Attachment("发票.pdf", "application/pdf", PDF)])
    stats = process_email(em, s, _config(), _no_dl, _no_qr, extract_fn=_fake_extract())
    assert stats.sources == 1
    assert stats.strong_sources == 1       # PDF 附件算强信号
    s.close()


def test_body_text_source_is_strong(tmp_path):
    s = _store(tmp_path)
    em = EmailMessage(uid=1, subject="发票", sender="a@b.com", date="",
                      body_text="发票号码 123 价税合计 100 税额 6 销售方 餐厅")
    stats = process_email(em, s, _config(), _no_dl, _no_qr, extract_fn=_fake_extract())
    assert stats.strong_sources == 1       # 正文发票文本算强信号
    s.close()
