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
from .models import SOURCE_TEXT, STATUS_PENDING, EmailMessage, PendingItem
from .normalize import NormalizeError, normalize
from .store import Store

log = logging.getLogger("fapiao")


@dataclass
class Stats:
    emails: int = 0
    sources: int = 0
    strong_sources: int = 0   # 强发票信号:发票附件 / 正文发票文本(不含正文链接、二维码下载)
    invoices_saved: int = 0
    duplicates: int = 0
    pending: int = 0
    errors: int = 0
    pending_reasons: list[str] = field(default_factory=list)


def _target_folder(part: Stats, config: Config) -> str | None:
    """根据单封邮件的处理结果决定该移入的文件夹;不该移则返回 None。

    避免把营销邮件误移:成功识别出发票就归「已处理」(不论来源);
    「待处理」只收有强发票信号(附件/正文发票文本)却没识别成功的邮件——
    纯营销邮件那种「正文链接能下到文件但不是发票」不算,留在收件箱。
      - 识别出发票(新入库或命中重复)            -> 已处理
      - 有强发票信号 但 没识别成功(失败/低置信/异常) -> 待处理
      - 其余(无来源、或仅靠链接/二维码且未成功)    -> 不移动
    """
    if not config.organize_folders:
        return None
    if part.invoices_saved > 0 or part.duplicates > 0:
        return config.folder_done
    if part.strong_sources > 0:
        return config.folder_pending
    return None


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
    stats.sources = len(acq.sources)
    # 强发票信号:发票附件(含压缩包内)或正文发票文本;正文链接/二维码下载的不算
    stats.strong_sources = sum(
        1 for s in acq.sources
        if s.kind == SOURCE_TEXT or s.origin.startswith(("附件", "压缩包"))
    )

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
    total.sources += part.sources
    total.strong_sources += part.strong_sources
    total.invoices_saved += part.invoices_saved
    total.duplicates += part.duplicates
    total.pending += part.pending
    total.errors += part.errors
    total.pending_reasons.extend(part.pending_reasons)


def _apply_moves(reader: MailReader, moves: list[tuple[int, str]], own_reader: bool) -> None:
    """收件结束后统一移动邮件。

    用全新连接执行:163 在拉取大邮件后可能掐断 socket,紧跟其后的 COPY 会失败;
    收件做完再用干净连接搬,移动更可靠。单封移动失败只记日志、不影响其余。
    """
    if own_reader:
        try:
            reader.close()
            reader.connect()
        except Exception:  # noqa: BLE001
            log.exception("移动阶段重连失败,本轮跳过移动(邮件已记 processed,不会重复处理)")
            return
    for uid, folder in moves:
        try:
            reader.move_message(uid, folder)
        except Exception:  # noqa: BLE001
            log.exception("移动邮件 uid=%s 到「%s」失败", uid, folder)
    reader.expunge()


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

    # 归类:确保两个目标文件夹存在;建不出来就本轮不移动
    organize = config.organize_folders
    if organize:
        organize = reader.ensure_folder(config.folder_done) and \
            reader.ensure_folder(config.folder_pending)

    moves: list[tuple[int, str]] = []  # (uid, 目标文件夹),收件结束后统一移动
    try:
        for em in reader.fetch_unprocessed(store.is_email_processed):
            try:
                part = process_email(em, store, config, downloader, qr_decoder)
                _merge(total, part)
                status = "ok" if part.invoices_saved else ("pending" if part.pending else "dup")
                store.mark_email_processed(em.uid, em.subject, em.sender, status)
                if organize:
                    folder = _target_folder(part, config)
                    if folder:
                        moves.append((em.uid, folder))
            except Exception:  # noqa: BLE001 单封邮件失败不阻塞整体
                log.exception("处理邮件 uid=%s 失败", em.uid)
                total.errors += 1
                store.mark_email_processed(em.uid, em.subject, em.sender, "error")
    finally:
        if organize and moves:
            _apply_moves(reader, moves, own_reader)
        if own_reader:
            reader.close()

    export_excel(store, config.output_file)
    store.close()
    return total


def rebuild(config: Config, downloader=None, qr_decoder=None,
            reader: MailReader | None = None) -> Stats:
    """灾难恢复:本地数据丢失后,从邮箱(含已归类的文件夹)重新拉取重建。

    遍历 INBOX + 已处理 + 待处理文件夹,对每封重新识别入库归档;
    发票按发票号去重,故可安全重复执行。不移动邮件、不写 processed_emails。
    """
    from .fetchers import decode_qr, make_downloader

    config.ensure_dirs()
    downloader = downloader or make_downloader(config.download_timeout, config.download_max_bytes)
    qr_decoder = qr_decoder or decode_qr

    store = Store(config.db_file, config.archive_dir)
    total = Stats()

    folders = [config.imap_folder, config.folder_done, config.folder_pending]

    own_reader = reader is None
    # 每个文件夹用独立连接:163 在大邮件之后可能掐断 socket,独立连接避免一个坏连接
    # 拖垮其余文件夹。不整折重试——发票都在「已处理/待处理」文件夹里(各自独立连接),
    # 即便 INBOX 偶发断连也不会少恢复发票;重试反而会把已扫过的邮件重复处理。
    for folder in folders:
        r = reader or MailReader(config)
        try:
            if own_reader:
                r.connect()
            for em in r.fetch_all(folder):
                try:
                    part = process_email(em, store, config, downloader, qr_decoder)
                    _merge(total, part)
                except Exception:  # noqa: BLE001 单封失败不阻塞重建
                    log.exception("重建时处理邮件 uid=%s 失败", em.uid)
                    total.errors += 1
        except Exception:  # noqa: BLE001 某文件夹读取失败(如连接被断开)不阻塞其余
            log.exception("重建时读取文件夹「%s」失败", folder)
            total.errors += 1
        finally:
            if own_reader:
                r.close()

    export_excel(store, config.output_file)
    store.close()
    return total
