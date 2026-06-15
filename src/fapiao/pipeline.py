"""流水线:串联 收件→来源提取→归一化→识别→去重入库→导出。

整条流程幂等:已处理邮件按 UID 跳过,发票按发票号码去重。
process_email 不依赖 IMAP,可单独测试。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .acquire import acquire_sources
from .config import Config
from .export import export_excel
from .extract import ExtractError, extract_invoice
from .ingest import MailReader
from .models import STATUS_PENDING, EmailMessage, PendingItem
from .normalize import NormalizeError, normalize
from .store import Store

log = logging.getLogger("fapiao")


@dataclass
class Stats:
    emails: int = 0
    invoices_saved: int = 0
    duplicates: int = 0
    pending: int = 0
    errors: int = 0
    pending_reasons: list[str] = field(default_factory=list)


def _add_pending(store: Store, em: EmailMessage, reason: str, stats: Stats, link: str = "") -> None:
    store.add_pending(PendingItem(
        email_uid=em.uid, subject=em.subject, sender=em.sender, reason=reason, link=link,
    ))
    stats.pending += 1
    stats.pending_reasons.append(reason)


def process_email(em: EmailMessage, store: Store, config: Config,
                  downloader, qr_decoder, extract_fn=extract_invoice) -> Stats:
    """处理单封邮件,把结果写入 store。返回本封邮件的增量统计。"""
    stats = Stats(emails=1)

    acq = acquire_sources(em, downloader, qr_decoder)

    # 来源提取阶段的失败(下载失败/无来源)记为待处理
    for reason in acq.pending_reasons:
        link = acq.links_found[0] if acq.links_found else ""
        _add_pending(store, em, reason, stats, link)

    for source in acq.sources:
        try:
            normalized = normalize(source)
        except NormalizeError as e:
            _add_pending(store, em, f"{source.origin}:归一化失败({e})", stats)
            continue

        try:
            record = extract_fn(normalized, config, em.uid)
        except ExtractError as e:
            _add_pending(store, em, f"{source.origin}:{e}", stats)
            continue
        except Exception as e:  # noqa: BLE001 兜底,单源失败不影响其他
            log.exception("识别异常")
            stats.errors += 1
            _add_pending(store, em, f"{source.origin}:识别异常({type(e).__name__})", stats)
            continue

        # 置信度过低 -> 待处理
        if record.confidence < config.min_confidence:
            record.status = STATUS_PENDING
            _add_pending(
                store, em,
                f"{source.origin}:置信度过低({record.confidence:.2f}),发票号 {record.发票号码}",
                stats,
            )
            continue

        # 去重
        if store.invoice_exists(record.发票号码):
            stats.duplicates += 1
            continue

        # 归档原始文件 + 入库
        record.archive_path = store.archive_file(record, source.data, _ext_for(source))
        if store.save_invoice(record):
            stats.invoices_saved += 1
        else:
            stats.duplicates += 1

    return stats


def _ext_for(source) -> str:
    if source.filename and "." in source.filename:
        return source.filename.rsplit(".", 1)[1]
    return {"pdf": "pdf", "ofd": "ofd", "image": "png", "text": "txt"}.get(source.kind, "bin")


def _merge(total: Stats, part: Stats) -> None:
    total.emails += part.emails
    total.invoices_saved += part.invoices_saved
    total.duplicates += part.duplicates
    total.pending += part.pending
    total.errors += part.errors
    total.pending_reasons.extend(part.pending_reasons)


def run(config: Config, downloader=None, qr_decoder=None,
        reader: MailReader | None = None) -> Stats:
    """跑一整轮:拉取未处理邮件 → 处理 → 导出 Excel。"""
    from .fetchers import decode_qr, make_downloader

    config.ensure_dirs()
    downloader = downloader or make_downloader(config.download_timeout, config.download_max_bytes)
    qr_decoder = qr_decoder or decode_qr

    store = Store(config.db_file, config.archive_dir)
    total = Stats()

    own_reader = reader is None
    reader = reader or MailReader(config)
    if own_reader:
        reader.connect()
    try:
        for em in reader.fetch_unprocessed(store.is_email_processed):
            try:
                part = process_email(em, store, config, downloader, qr_decoder)
                _merge(total, part)
                status = "ok" if part.invoices_saved else ("pending" if part.pending else "dup")
                store.mark_email_processed(em.uid, em.subject, em.sender, status)
            except Exception:  # noqa: BLE001 单封邮件失败不阻塞整体
                log.exception("处理邮件 uid=%s 失败", em.uid)
                total.errors += 1
                store.mark_email_processed(em.uid, em.subject, em.sender, "error")
    finally:
        if own_reader:
            reader.close()

    export_excel(store, config.output_file)
    store.close()
    return total
