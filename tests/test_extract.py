"""extract 的纯函数测试:解析 JSON、映射记录、提取流程(假 AI)。"""

import pytest

from fapiao.config import Config
from fapiao.extract import (
    ExtractError,
    extract_invoice,
    parse_response,
    record_from_data,
)
from fapiao.models import MODE_IMAGE, MODE_TEXT, InvoiceSource, NormalizedInput

GOOD_JSON = """好的,结果如下:
```json
{"发票号码": "24317000000123456789", "开票日期": "2026-06-01",
 "发票类型": "数电普通发票", "销售方名称": "某某餐饮", "金额": 94.34,
 "税率": "6%", "税额": 5.66, "价税合计": 100.0,
 "消费明细": [{"名称": "餐饮服务", "金额": 94.34}],
 "is_invoice": true, "confidence": 0.95}
```"""


def _config():
    return Config(imap_host="", imap_port=993, imap_user="", imap_password="", min_confidence=0.6)


def test_parse_response_with_fence():
    data = parse_response(GOOD_JSON)
    assert data["发票号码"] == "24317000000123456789"
    assert data["价税合计"] == 100.0


def test_parse_response_bare_json():
    data = parse_response('{"发票号码": "X", "金额": 1}')
    assert data["发票号码"] == "X"


def test_parse_response_invalid_raises():
    with pytest.raises(ExtractError):
        parse_response("这不是 JSON")


def test_record_from_data_maps_and_cleans():
    data = parse_response(GOOD_JSON)
    src = InvoiceSource(kind="pdf", origin="附件:a.pdf")
    norm = NormalizedInput(mode=MODE_TEXT, source=src)
    rec = record_from_data(data, norm, uid=10, raw=GOOD_JSON)
    assert rec.发票号码 == "24317000000123456789"
    assert rec.金额 == 94.34
    assert rec.confidence == 0.95
    assert rec.source_email_uid == 10
    assert rec.source_origin == "附件:a.pdf"


def test_record_handles_currency_strings():
    rec = record_from_data({"发票号码": "1", "价税合计": "￥1,234.50", "confidence": "0.8"},
                           NormalizedInput(mode=MODE_TEXT), uid=0, raw="")
    assert rec.价税合计 == 1234.50
    assert rec.confidence == 0.8


def test_extract_invoice_text_path():
    norm = NormalizedInput(mode=MODE_TEXT, text="发票...")
    rec = extract_invoice(norm, _config(), uid=1, text_fn=lambda t, c: GOOD_JSON)
    assert rec.发票号码 == "24317000000123456789"


def test_extract_invoice_vision_path():
    norm = NormalizedInput(mode=MODE_IMAGE, images=[b"img"])
    rec = extract_invoice(norm, _config(), uid=2, vision_fn=lambda imgs, c: GOOD_JSON)
    assert rec.发票类型 == "数电普通发票"


def test_extract_not_invoice_raises():
    norm = NormalizedInput(mode=MODE_TEXT, text="x")
    with pytest.raises(ExtractError):
        extract_invoice(norm, _config(), text_fn=lambda t, c: '{"is_invoice": false}')


def test_extract_missing_number_raises():
    norm = NormalizedInput(mode=MODE_TEXT, text="x")
    with pytest.raises(ExtractError):
        extract_invoice(norm, _config(), text_fn=lambda t, c: '{"is_invoice": true, "金额": 1}')
