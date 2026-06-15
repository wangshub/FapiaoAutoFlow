"""来源提取:从一封邮件里按优先级提取「待识别的发票来源」。

优先级:
  1. 附件(PDF / OFD / 图片;zip 内递归一层)
  2. 正文下载链接 → 下载
  3. 正文/附件图片里的二维码 → 解码出链接 → 下载
  4. 正文纯文本(含发票关键词)

下载需要登录 / 链接失效 / 二维码解不出 → 记入 pending_reasons。
下载器与二维码解码器通过参数注入,便于测试。
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Callable, Optional

from .models import (
    SOURCE_IMAGE,
    SOURCE_OFD,
    SOURCE_PDF,
    SOURCE_TEXT,
    Attachment,
    EmailMessage,
    InvoiceSource,
)

IMAGE_EXTS = {"jpg", "jpeg", "png", "bmp", "gif", "tiff", "webp"}
URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)
# 正文里出现这些词,才认为正文本身可能是一张发票(避免把普通邮件正文乱识别)
INVOICE_KEYWORDS = ("发票", "价税合计", "fapiao", "invoice", "税额", "开票")


@dataclass
class AcquireResult:
    sources: list[InvoiceSource] = field(default_factory=list)
    pending_reasons: list[str] = field(default_factory=list)
    links_found: list[str] = field(default_factory=list)


# 下载器签名:url -> (data, content_type) 或 None(失败)
Downloader = Callable[[str], Optional[tuple[bytes, str]]]
# 二维码解码器签名:image_bytes -> [url, ...]
QRDecoder = Callable[[bytes], list[str]]


def _ext_of(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


def _classify_file(filename: str, content_type: str, data: bytes) -> Optional[str]:
    """根据文件名/类型/魔数判断发票文件类型,无法识别返回 None。"""
    ext = _ext_of(filename)
    ct = (content_type or "").lower()

    if ext == "pdf" or "pdf" in ct or data[:5] == b"%PDF-":
        return SOURCE_PDF
    if ext == "ofd":
        return SOURCE_OFD
    if ext in IMAGE_EXTS or ct.startswith("image/"):
        return SOURCE_IMAGE
    # OFD/zip 都是 zip 容器;靠扩展名区分,这里交给调用方处理 zip
    return None


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_html_page(data: bytes, content_type: str) -> bool:
    """下载回来的是网页(多半要登录/JS 渲染),不是发票文件。"""
    if "text/html" in (content_type or "").lower():
        return True
    head = data[:512].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _ext_from_download(url: str, content_type: str, kind: str) -> str:
    ct = (content_type or "").lower()
    if kind == SOURCE_PDF:
        return "pdf"
    if kind == SOURCE_OFD:
        return "ofd"
    for ext in IMAGE_EXTS:
        if ext in ct or url.lower().rsplit(".", 1)[-1] == ext:
            return ext
    return "bin"


def _sources_from_attachment(att: Attachment) -> list[InvoiceSource]:
    """把一个附件转成 0~N 个发票来源(zip 会递归一层)。"""
    ext = att.ext
    if ext == "zip" or att.content_type.lower() in ("application/zip", "application/x-zip-compressed"):
        return _sources_from_zip(att)

    kind = _classify_file(att.filename, att.content_type, att.data)
    if kind is None:
        return []
    return [InvoiceSource(kind=kind, origin=f"附件:{att.filename}", data=att.data, filename=att.filename)]


def _sources_from_zip(att: Attachment) -> list[InvoiceSource]:
    out: list[InvoiceSource] = []
    try:
        with zipfile.ZipFile(io.BytesIO(att.data)) as zf:
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                data = zf.read(name)
                kind = _classify_file(name, "", data)
                if kind is not None:
                    out.append(
                        InvoiceSource(kind=kind, origin=f"压缩包 {att.filename} 内:{name}",
                                      data=data, filename=name.rsplit("/", 1)[-1])
                    )
    except (zipfile.BadZipFile, OSError):
        pass
    return out


def _download_to_source(url: str, origin: str, downloader: Downloader,
                        result: AcquireResult) -> bool:
    """尝试下载一个链接并加入来源。成功 True,失败把原因记入 pending 并返回 False。"""
    try:
        got = downloader(url)
    except Exception as e:  # 网络异常等
        result.pending_reasons.append(f"{origin}下载异常({type(e).__name__})")
        return False
    if got is None:
        result.pending_reasons.append(f"{origin}下载失败或需登录")
        return False
    data, content_type = got
    if _is_html_page(data, content_type):
        result.pending_reasons.append(f"{origin}指向网页(可能需登录/JS 渲染)")
        return False
    kind = _classify_file(url, content_type, data)
    if kind is None:
        result.pending_reasons.append(f"{origin}下载内容非发票文件")
        return False
    ext = _ext_from_download(url, content_type, kind)
    result.sources.append(InvoiceSource(kind=kind, origin=origin, data=data,
                                        filename=f"download.{ext}"))
    return True


def acquire_sources(em: EmailMessage, downloader: Downloader,
                    qr_decoder: QRDecoder) -> AcquireResult:
    """从邮件提取发票来源。downloader / qr_decoder 由调用方注入。"""
    result = AcquireResult()

    # 1. 附件优先
    for att in em.attachments:
        result.sources.extend(_sources_from_attachment(att))

    if result.sources:
        return result

    body = em.body_text or _strip_html(em.body_html)

    # 2. 正文下载链接
    links = URL_RE.findall(em.body_text + " " + em.body_html)
    result.links_found.extend(links)
    for url in links:
        _download_to_source(url, "正文链接", downloader, result)

    if result.sources:
        return result

    # 3. 二维码(正文内嵌图 + 图片附件)
    images = [img.data for img in em.inline_images]
    images += [a.data for a in em.attachments if a.ext in IMAGE_EXTS]
    for img_data in images:
        try:
            qr_urls = qr_decoder(img_data)
        except Exception:
            qr_urls = []
        for url in qr_urls:
            result.links_found.append(url)
            _download_to_source(url, "二维码链接", downloader, result)

    if result.sources:
        return result

    # 4. 正文纯文本(含发票关键词)
    if body and any(k in body for k in INVOICE_KEYWORDS):
        result.sources.append(InvoiceSource(kind=SOURCE_TEXT, origin="邮件正文", text=body))

    if not result.sources and not result.pending_reasons:
        result.pending_reasons.append("邮件中未找到任何发票来源")

    return result
