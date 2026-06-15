"""命令行入口:python -m fapiao run"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .export import export_excel
from .store import Store


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def cmd_run(args) -> int:
    from .pipeline import run

    config = load_config(args.config)
    stats = run(config)
    print(
        f"完成:邮件 {stats.emails} 封 | 新入库 {stats.invoices_saved} 张 | "
        f"重复 {stats.duplicates} | 待处理 {stats.pending} | 错误 {stats.errors}"
    )
    print(f"汇总已导出:{config.output_file}")
    if stats.pending:
        print("待处理(节选):")
        for r in stats.pending_reasons[:10]:
            print(f"  - {r}")
    return 0


def cmd_export(args) -> int:
    """只重新生成 Excel,不收件。"""
    config = load_config(args.config)
    store = Store(config.db_file, config.archive_dir)
    path = export_excel(store, config.output_file)
    store.close()
    print(f"已导出:{path}")
    return 0


def cmd_init(args) -> int:
    """交互式生成 config.yaml。"""
    from .init import run_init

    return run_init(args.config)


def cmd_rebuild(args) -> int:
    """灾难恢复:从邮箱(含已归类文件夹)重新拉取重建本地数据。"""
    from .pipeline import rebuild

    config = load_config(args.config)
    stats = rebuild(config)
    print(
        f"重建完成:扫描邮件 {stats.emails} 封 | 入库 {stats.invoices_saved} 张 | "
        f"重复 {stats.duplicates} | 待处理 {stats.pending} | 错误 {stats.errors}"
    )
    print(f"汇总已导出:{config.output_file}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="fapiao", description="发票邮件自动识别归档")
    parser.add_argument("-c", "--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="交互式生成 config.yaml(首次使用)")
    p_init.set_defaults(func=cmd_init)

    p_run = sub.add_parser("run", help="收件并识别、入库、导出")
    p_run.set_defaults(func=cmd_run)

    p_export = sub.add_parser("export", help="仅根据现有数据重新生成 Excel")
    p_export.set_defaults(func=cmd_export)

    p_rebuild = sub.add_parser("rebuild", help="灾难恢复:从邮箱归档文件夹重建本地数据")
    p_rebuild.set_defaults(func=cmd_rebuild)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
