"""normalize 归一化测试。PDF 用 PyMuPDF 现造一个带文字层的样例。"""

import pytest

from fapiao.models import (
    MODE_IMAGE,
    MODE_TEXT,
    SOURCE_IMAGE,
    SOURCE_PDF,
    SOURCE_TEXT,
    InvoiceSource,
)
from fapiao.normalize import (
    NormalizeError,
    _ofd_collect_text,
    normalize,
    text_is_sufficient,
)


def test_ofd_collect_text_walks_nested():
    parsed = [{"page": [{"text": "发票号码"}, {"x": {"text": "123"}}]}]
    assert _ofd_collect_text(parsed) == "发票号码 123"


def test_ofd_collect_text_dedups_repeated_page():
    # easyofd 常把整页文本重复多份;按页首再现裁掉重复
    parsed = [{"text": "电子发票"}, {"text": "号码"},
              {"text": "电子发票"}, {"text": "号码"}]
    assert _ofd_collect_text(parsed) == "电子发票 号码"


def test_text_is_sufficient():
    assert text_is_sufficient("发票号码 123 价税合计 100 税额 6 销售方 餐厅有限公司")
    assert not text_is_sufficient("")
    assert not text_is_sufficient("hi")                 # 太短
    assert not text_is_sufficient("a" * 100)            # 够长但无关键词


def test_text_source():
    src = InvoiceSource(kind=SOURCE_TEXT, origin="正文", text="发票内容")
    n = normalize(src)
    assert n.mode == MODE_TEXT
    assert n.text == "发票内容"


def test_image_source():
    src = InvoiceSource(kind=SOURCE_IMAGE, origin="附件", data=b"\xff\xd8jpg")
    n = normalize(src)
    assert n.mode == MODE_IMAGE
    assert n.images == [b"\xff\xd8jpg"]


def test_empty_image_raises():
    with pytest.raises(NormalizeError):
        normalize(InvoiceSource(kind=SOURCE_IMAGE, origin="x", data=b""))


def _make_text_pdf() -> bytes:
    fitz = pytest.importorskip("fitz")

    doc = fitz.open()
    page = doc.new_page()
    # fitz 默认 Helvetica 不能嵌入中文,用 ASCII 文本(含关键词 invoice)
    page.insert_text((72, 72),
                     "Electronic invoice No 24317000000123 Total 100.00 Tax 5.66 Seller ABC Restaurant")
    data = doc.tobytes()
    doc.close()
    return data


def test_pdf_with_text_layer_goes_text():
    src = InvoiceSource(kind=SOURCE_PDF, origin="附件:a.pdf", data=_make_text_pdf(),
                        filename="a.pdf")
    n = normalize(src)
    assert n.mode == MODE_TEXT
    assert "invoice" in n.text.lower()


def test_pdf_without_text_layer_goes_image():
    fitz = pytest.importorskip("fitz")

    doc = fitz.open()
    doc.new_page()          # 空白页,无文字层
    data = doc.tobytes()
    doc.close()
    src = InvoiceSource(kind=SOURCE_PDF, origin="附件:blank.pdf", data=data, filename="blank.pdf")
    n = normalize(src)
    assert n.mode == MODE_IMAGE
    assert len(n.images) >= 1
    assert n.images[0][:8] == b"\x89PNG\r\n\x1a\n"   # 渲染成 PNG
