"""ingest.parse_email 测试:用 stdlib 构造原始邮件字节。"""

from email.message import EmailMessage as PyEmail

from fapiao.ingest import parse_email


def _build(subject, body, attachments=None, inline_images=None) -> bytes:
    msg = PyEmail()
    msg["Subject"] = subject
    msg["From"] = "餐厅 <restaurant@example.com>"
    msg["Date"] = "Mon, 01 Jun 2026 12:00:00 +0800"
    msg.set_content(body)
    for fn, ctype, data in attachments or []:
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=fn)
    for cid, ctype, data in inline_images or []:
        maintype, subtype = ctype.split("/", 1)
        msg.add_related(data, maintype=maintype, subtype=subtype, cid=cid)
    return msg.as_bytes()


def test_parse_basic_headers_and_body():
    raw = _build("你的发票", "请查收发票附件")
    em = parse_email(42, raw)
    assert em.uid == 42
    assert em.subject == "你的发票"
    assert "restaurant@example.com" in em.sender
    assert "请查收" in em.body_text


def test_parse_with_pdf_attachment():
    raw = _build("发票", "见附件", attachments=[("发票.pdf", "application/pdf", b"%PDF-1.4")])
    em = parse_email(1, raw)
    assert len(em.attachments) == 1
    assert em.attachments[0].filename == "发票.pdf"
    assert em.attachments[0].ext == "pdf"
    assert em.attachments[0].data == b"%PDF-1.4"


def test_parse_with_inline_image():
    raw = _build("发票", "二维码见图",
                 inline_images=[("<qr1>", "image/png", b"\x89PNG\r\n\x1a\n")])
    em = parse_email(2, raw)
    assert len(em.inline_images) == 1
    assert em.inline_images[0].content_type == "image/png"


def test_fetch_all_retries_on_abort_then_continues(monkeypatch):
    """163 中途掐断:fetch_all 应重连重试同一封、不漏不跳,完整扫完。"""
    from fapiao.config import Config
    from fapiao.ingest import MailReader

    reader = MailReader(Config(imap_host="x", imap_port=993, imap_user="u", imap_password="p"))

    class FakeClient:
        def __init__(self):
            self.aborted_once = set()

        def folder_exists(self, f):
            return True

        def select_folder(self, f):
            pass

        def search(self, q):
            return [3, 1, 2]          # 乱序,验证内部会排序

        def fetch(self, uids, parts):
            uid = uids[0]
            if uid == 2 and uid not in self.aborted_once:   # uid=2 第一次断连
                self.aborted_once.add(uid)
                raise OSError("socket error")
            return {uid: {b"RFC822": _build("发票", f"body {uid}")}}

    reader.client = FakeClient()
    reconnects = []
    monkeypatch.setattr(reader, "_reconnect", lambda: reconnects.append(1))

    got = [em.uid for em in reader.fetch_all("发票已处理")]
    assert got == [1, 2, 3]          # 一封不少,顺序正确
    assert len(reconnects) == 1       # 只重连了一次(重试 uid=2 成功)
