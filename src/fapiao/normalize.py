"""归一化:把不同格式的发票来源转成可直接喂大模型的 NormalizedInput。

  - 文本来源        -> 文本模式
  - PDF             -> 有文字层走文本模式;否则渲染成图走视觉模式
  - 图片            -> 视觉模式
  - OFD             -> 用 easyofd 抽文字/转图;失败抛 NormalizeError(由 pipeline 记 pending)
"""

from __future__ import annotations

import io

from .models import (
    MODE_IMAGE,
    MODE_TEXT,
    SOURCE_IMAGE,
    SOURCE_OFD,
    SOURCE_PDF,
    SOURCE_TEXT,
    InvoiceSource,
    NormalizedInput,
)

INVOICE_KEYWORDS = ("发票", "价税合计", "金额", "税额", "开票", "invoice")
# 文字层「足够」用于识别的最小长度
MIN_TEXT_LEN = 30


class NormalizeError(Exception):
    """无法把来源归一化(如 OFD 解析失败),应记入待处理。"""


def text_is_sufficient(text: str) -> bool:
    """判断抽出的文字层是否足以直接做文本识别。"""
    if not text:
        return False
    stripped = text.strip()
    if len(stripped) < MIN_TEXT_LEN:
        return False
    low = stripped.lower()
    return any(k in low for k in INVOICE_KEYWORDS)


def _pdf_extract_text(data: bytes) -> str:
    import pdfplumber

    parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _pdf_render_images(data: bytes, max_pages: int = 3) -> list[bytes]:
    import fitz  # PyMuPDF

    images = []
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        for page in doc[:max_pages]:
            pix = page.get_pixmap(dpi=200)
            images.append(pix.tobytes("png"))
    finally:
        doc.close()
    return images


def _ofd_to_input(source: InvoiceSource) -> NormalizedInput:
    try:
        from easyofd import OFD
    except Exception as e:
        raise NormalizeError(f"OFD 解析库不可用:{e}")

    try:
        ofd = OFD()
        ofd.read(source.data, format="bytes")
        text = ofd.to_txt() or ""
        if text_is_sufficient(text):
            return NormalizedInput(mode=MODE_TEXT, text=text, source=source)
        # 没有足够文字层 -> 转图走视觉
        import base64

        imgs = ofd.to_jpg() or []
        image_bytes = []
        for img in imgs:
            if isinstance(img, str):       # base64 字符串
                image_bytes.append(base64.b64decode(img))
            elif isinstance(img, (bytes, bytearray)):
                image_bytes.append(bytes(img))
        if not image_bytes:
            raise NormalizeError("OFD 既无文字层也无法转图")
        return NormalizedInput(mode=MODE_IMAGE, images=image_bytes, source=source)
    except NormalizeError:
        raise
    except Exception as e:
        raise NormalizeError(f"OFD 解析失败:{e}")


def normalize(source: InvoiceSource) -> NormalizedInput:
    """把一个 InvoiceSource 归一化。失败抛 NormalizeError。"""
    if source.kind == SOURCE_TEXT:
        return NormalizedInput(mode=MODE_TEXT, text=source.text, source=source)

    if source.kind == SOURCE_IMAGE:
        if not source.data:
            raise NormalizeError("图片来源为空")
        return NormalizedInput(mode=MODE_IMAGE, images=[source.data], source=source)

    if source.kind == SOURCE_PDF:
        try:
            text = _pdf_extract_text(source.data)
        except Exception:
            text = ""
        if text_is_sufficient(text):
            return NormalizedInput(mode=MODE_TEXT, text=text, source=source)
        try:
            images = _pdf_render_images(source.data)
        except Exception as e:
            raise NormalizeError(f"PDF 无文字层且渲染失败:{e}")
        if not images:
            raise NormalizeError("PDF 渲染未得到图片")
        return NormalizedInput(mode=MODE_IMAGE, images=images, source=source)

    if source.kind == SOURCE_OFD:
        return _ofd_to_input(source)

    raise NormalizeError(f"未知来源类型:{source.kind}")
