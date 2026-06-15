"""SQLite 状态库 + 原始发票归档。

SQLite 是唯一事实来源:
  - processed_emails: 已处理邮件 UID(增量收件去重 / 省 API)
  - invoices:         识别成功的发票(发票号码唯一,去重)
  - pending:          无法自动处理、需人工补录的条目
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from .models import InvoiceRecord, PendingItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_emails (
    uid        INTEGER PRIMARY KEY,
    subject    TEXT,
    sender     TEXT,
    status     TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS invoices (
    发票号码    TEXT PRIMARY KEY,
    发票代码    TEXT,
    开票日期    TEXT,
    发票类型    TEXT,
    销售方名称  TEXT,
    销售方税号  TEXT,
    购买方名称  TEXT,
    购买方税号  TEXT,
    金额        REAL,
    税率        TEXT,
    税额        REAL,
    价税合计    REAL,
    消费明细    TEXT,
    备注        TEXT,
    confidence  REAL,
    source_email_uid INTEGER,
    source_origin    TEXT,
    archive_path     TEXT,
    status      TEXT,
    raw_json    TEXT,
    created_at  TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS pending (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email_uid  INTEGER,
    subject    TEXT,
    sender     TEXT,
    reason     TEXT,
    link       TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""


def _safe_filename(name: str) -> str:
    """清理成可用作文件名的字符串。"""
    name = re.sub(r"[^\w一-鿿.-]", "_", name)
    return name.strip("_") or "invoice"


def _year_month(开票日期: str) -> tuple[str, str]:
    """从开票日期里解析 (年, 月)。识别 2026-06-14 / 2026年06月14日 / 20260614。"""
    joined = "".join(re.findall(r"\d+", 开票日期 or ""))
    if len(joined) >= 6:
        return joined[0:4], joined[4:6]
    return "unknown", "unknown"


class Store:
    def __init__(self, db_file: str | Path, archive_dir: str | Path):
        self.db_file = Path(db_file)
        self.archive_dir = Path(archive_dir)
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_file))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---- 邮件去重 ----
    def is_email_processed(self, uid: int) -> bool:
        cur = self.conn.execute("SELECT 1 FROM processed_emails WHERE uid = ?", (uid,))
        return cur.fetchone() is not None

    def mark_email_processed(self, uid: int, subject: str, sender: str, status: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO processed_emails (uid, subject, sender, status) "
            "VALUES (?, ?, ?, ?)",
            (uid, subject, sender, status),
        )
        self.conn.commit()

    # ---- 发票去重入库 ----
    def invoice_exists(self, 发票号码: str) -> bool:
        if not 发票号码:
            return False
        cur = self.conn.execute("SELECT 1 FROM invoices WHERE 发票号码 = ?", (发票号码,))
        return cur.fetchone() is not None

    def archive_file(self, record: InvoiceRecord, source_data: bytes, ext: str) -> str:
        """把原始发票文件写入 archive_dir/年/月/<发票号>.<ext>,返回路径字符串。"""
        if not source_data:
            return ""
        year, month = _year_month(record.开票日期)
        folder = self.archive_dir / year / month
        folder.mkdir(parents=True, exist_ok=True)
        base = _safe_filename(record.发票号码 or "invoice")
        ext = (ext or "bin").lstrip(".")
        path = folder / f"{base}.{ext}"
        path.write_bytes(source_data)
        return str(path)

    def save_invoice(self, record: InvoiceRecord) -> bool:
        """写入一张发票。已存在(同发票号码)则跳过,返回 False。"""
        if self.invoice_exists(record.发票号码):
            return False
        self.conn.execute(
            """INSERT INTO invoices (
                发票号码, 发票代码, 开票日期, 发票类型,
                销售方名称, 销售方税号, 购买方名称, 购买方税号,
                金额, 税率, 税额, 价税合计, 消费明细, 备注,
                confidence, source_email_uid, source_origin, archive_path, status, raw_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record.发票号码, record.发票代码, record.开票日期, record.发票类型,
                record.销售方名称, record.销售方税号, record.购买方名称, record.购买方税号,
                record.金额, record.税率, record.税额, record.价税合计,
                json.dumps(record.消费明细, ensure_ascii=False), record.备注,
                record.confidence, record.source_email_uid, record.source_origin,
                record.archive_path, record.status, record.raw_json,
            ),
        )
        self.conn.commit()
        return True

    # ---- 待处理 ----
    def add_pending(self, item: PendingItem) -> None:
        self.conn.execute(
            "INSERT INTO pending (email_uid, subject, sender, reason, link) "
            "VALUES (?, ?, ?, ?, ?)",
            (item.email_uid, item.subject, item.sender, item.reason, item.link),
        )
        self.conn.commit()

    # ---- 查询(导出用)----
    def all_invoices(self) -> list[sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM invoices ORDER BY 开票日期 DESC, 发票号码")
        return cur.fetchall()

    def all_pending(self) -> list[sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM pending ORDER BY created_at DESC")
        return cur.fetchall()
