"""阶段之间传递的数据结构。

整条流水线的数据流:
    EmailMessage  --acquire-->  InvoiceSource  --normalize-->  NormalizedInput
                  --extract-->  InvoiceRecord / PendingItem
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Attachment:
    """一封邮件里的一个附件。"""

    filename: str
    content_type: str
    data: bytes

    @property
    def ext(self) -> str:
        """小写扩展名,不含点。例如 'pdf'。"""
        _, _, ext = self.filename.rpartition(".")
        return ext.lower() if "." in self.filename else ""


@dataclass
class EmailMessage:
    """从 IMAP 拉取并解析后的一封邮件。"""

    uid: int
    subject: str
    sender: str
    date: str
    body_text: str = ""
    body_html: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    # 正文中内嵌的图片(cid 图),用于二维码解码
    inline_images: list[Attachment] = field(default_factory=list)


# 发票来源的类型
SOURCE_PDF = "pdf"
SOURCE_OFD = "ofd"
SOURCE_IMAGE = "image"
SOURCE_TEXT = "text"


@dataclass
class InvoiceSource:
    """从邮件里提取出来的、一份待识别的发票来源。

    一封邮件可能产出 0~N 个来源(多张发票附件)。
    """

    kind: str                       # SOURCE_PDF / SOURCE_OFD / SOURCE_IMAGE / SOURCE_TEXT
    origin: str                     # 人类可读的来源说明,如 "附件:发票.pdf" / "二维码链接"
    data: bytes = b""               # 文件字节(text 来源为空)
    text: str = ""                  # 文本内容(仅 text 来源)
    filename: str = ""              # 原始文件名(用于归档命名/扩展名)


# normalize 产出的输入模式
MODE_TEXT = "text"
MODE_IMAGE = "image"


@dataclass
class NormalizedInput:
    """归一化后、可直接喂给大模型的输入。"""

    mode: str                       # MODE_TEXT 走文本模型 / MODE_IMAGE 走视觉模型
    text: str = ""                  # mode==text 时的发票文字
    images: list[bytes] = field(default_factory=list)  # mode==image 时的 PNG 图片字节
    source: Optional[InvoiceSource] = None             # 关联的原始来源(用于归档)


# 发票记录状态
STATUS_OK = "已识别"
STATUS_PENDING = "待处理"
STATUS_REIMBURSED = "已报销"


@dataclass
class InvoiceRecord:
    """识别成功的一张发票。字段尽量覆盖增值税发票全要素。"""

    发票号码: str = ""
    发票代码: str = ""
    开票日期: str = ""
    发票类型: str = ""
    销售方名称: str = ""
    销售方税号: str = ""
    购买方名称: str = ""
    购买方税号: str = ""
    金额: Optional[float] = None        # 不含税金额
    税率: str = ""
    税额: Optional[float] = None
    价税合计: Optional[float] = None
    消费明细: list[dict[str, Any]] = field(default_factory=list)
    备注: str = ""

    # 元数据
    confidence: float = 0.0
    source_email_uid: int = 0
    source_origin: str = ""
    archive_path: str = ""
    status: str = STATUS_OK
    raw_json: str = ""                  # 模型原始返回,便于追溯/补字段


@dataclass
class PendingItem:
    """无法自动处理、需人工补录的邮件/来源。"""

    email_uid: int
    subject: str
    sender: str
    reason: str
    link: str = ""
