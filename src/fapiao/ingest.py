"""收件:连接 IMAP,增量拉取未处理邮件并解析为 EmailMessage。

解析逻辑(parse_email)与网络连接(MailReader)分离,便于测试。
"""

from __future__ import annotations

import email
from email.header import decode_header, make_header
from email.message import Message
from typing import Iterator, Optional

from .models import Attachment, EmailMessage


def _decode(value: Optional[str]) -> str:
    """解码可能经过 MIME 编码的邮件头(如主题、发件人)。"""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _part_text(part: Message) -> str:
    """解码一个文本 part 的正文。"""
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, TypeError):
        return payload.decode("utf-8", errors="replace")


def parse_email(uid: int, raw_bytes: bytes) -> EmailMessage:
    """把 RFC822 原始字节解析为 EmailMessage(纯函数,不触网)。"""
    msg = email.message_from_bytes(raw_bytes)

    em = EmailMessage(
        uid=uid,
        subject=_decode(msg.get("Subject")),
        sender=_decode(msg.get("From")),
        date=msg.get("Date", ""),
    )

    for part in msg.walk():
        if part.is_multipart():
            continue

        content_type = part.get_content_type()
        disposition = (part.get("Content-Disposition") or "").lower()
        filename = part.get_filename()
        if filename:
            filename = _decode(filename)

        # 附件:有文件名,或显式 attachment
        is_attachment = bool(filename) or "attachment" in disposition
        is_inline_image = content_type.startswith("image/") and not is_attachment

        if is_attachment:
            data = part.get_payload(decode=True) or b""
            em.attachments.append(
                Attachment(filename=filename or "attachment", content_type=content_type, data=data)
            )
        elif is_inline_image:
            data = part.get_payload(decode=True) or b""
            if data:
                em.inline_images.append(
                    Attachment(filename=filename or "inline", content_type=content_type, data=data)
                )
        elif content_type == "text/plain":
            em.body_text += _part_text(part)
        elif content_type == "text/html":
            em.body_html += _part_text(part)

    return em


class MailReader:
    """IMAP 连接与增量拉取。用法:

        with MailReader(config) as reader:
            for em in reader.fetch_unprocessed(is_processed=store.is_email_processed):
                ...
    """

    def __init__(self, config):
        self.config = config
        self.client = None

    def __enter__(self) -> "MailReader":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def connect(self) -> None:
        from imapclient import IMAPClient

        if not self.config.imap_host or not self.config.imap_user:
            raise RuntimeError("IMAP 未配置:请在 .env 填写 IMAP_HOST / IMAP_USER / IMAP_PASSWORD")

        self.client = IMAPClient(self.config.imap_host, port=self.config.imap_port, ssl=True)
        self.client.login(self.config.imap_user, self.config.imap_password)
        # 163/126/QQ 等网易系要求第三方客户端先发 ID,否则后续命令可能被判「Unsafe Login」
        try:
            self.client.id_({"name": "FapiaoAutoFlow", "version": "0.1.0",
                             "vendor": "fapiao", "contact": self.config.imap_user})
        except Exception:  # noqa: BLE001 不支持 ID 的服务器忽略即可
            pass
        self.client.select_folder(self.config.imap_folder)

    def close(self) -> None:
        if self.client is not None:
            try:
                self.client.logout()
            except Exception:  # noqa: BLE001 163 常在 LOGOUT 时直接断开 socket,忽略即可
                pass
            finally:
                self.client = None

    def fetch_unprocessed(self, is_processed) -> Iterator[EmailMessage]:
        """拉取尚未处理的邮件。is_processed(uid)->bool 用于跳过已处理。

        按 UID 升序处理,最多 fetch_limit 封。
        """
        assert self.client is not None, "请先 connect()"
        uids = self.client.search(["ALL"])
        uids = sorted(uids)

        count = 0
        for uid in uids:
            if count >= self.config.fetch_limit:
                break
            if is_processed(uid):
                continue
            resp = self.client.fetch([uid], ["RFC822"])
            raw = resp.get(uid, {}).get(b"RFC822")
            if not raw:
                continue
            yield parse_email(uid, raw)
            count += 1
