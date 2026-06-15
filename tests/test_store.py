"""store 去重入库 + 归档测试。"""

from fapiao.models import InvoiceRecord, PendingItem
from fapiao.store import Store


def _store(tmp_path):
    return Store(tmp_path / "db.sqlite", tmp_path / "archive")


def test_email_processed_roundtrip(tmp_path):
    s = _store(tmp_path)
    assert not s.is_email_processed(1)
    s.mark_email_processed(1, "主题", "a@b.com", "ok")
    assert s.is_email_processed(1)
    s.close()


def test_save_and_dedup(tmp_path):
    s = _store(tmp_path)
    rec = InvoiceRecord(发票号码="INV001", 开票日期="2026-06-01", 价税合计=100.0)
    assert s.save_invoice(rec) is True
    # 相同发票号码 -> 不重复入库
    assert s.save_invoice(InvoiceRecord(发票号码="INV001", 价税合计=999)) is False
    assert len(s.all_invoices()) == 1
    s.close()


def test_archive_path_uses_year_month(tmp_path):
    s = _store(tmp_path)
    rec = InvoiceRecord(发票号码="INV9", 开票日期="2026-06-01")
    path = s.archive_file(rec, b"%PDF-data", "pdf")
    assert path
    assert "2026" in path and "06" in path
    assert path.endswith("INV9.pdf")
    from pathlib import Path
    assert Path(path).read_bytes() == b"%PDF-data"
    s.close()


def test_archive_unknown_date(tmp_path):
    s = _store(tmp_path)
    rec = InvoiceRecord(发票号码="INV0", 开票日期="")
    path = s.archive_file(rec, b"x", "png")
    assert "unknown" in path
    s.close()


def test_pending(tmp_path):
    s = _store(tmp_path)
    s.add_pending(PendingItem(email_uid=5, subject="发票", sender="a@b.com",
                              reason="需登录", link="http://x"))
    rows = s.all_pending()
    assert len(rows) == 1
    assert rows[0]["reason"] == "需登录"
    s.close()


def test_invoice_fields_persisted(tmp_path):
    s = _store(tmp_path)
    rec = InvoiceRecord(发票号码="INV2", 销售方名称="餐厅", 金额=94.34, 税额=5.66,
                        价税合计=100.0, 消费明细=[{"名称": "餐饮"}], confidence=0.9)
    s.save_invoice(rec)
    row = s.all_invoices()[0]
    assert row["销售方名称"] == "餐厅"
    assert row["价税合计"] == 100.0
    assert "餐饮" in row["消费明细"]
    s.close()
