"""配置加载:全部配置(含账号/密钥)来自 config.yaml。

config.yaml 含敏感信息,已被 .gitignore 忽略,请勿提交;模板见 config.example.yaml。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Config:
    # 邮箱
    imap_host: str
    imap_port: int
    imap_user: str
    imap_password: str
    imap_folder: str = "INBOX"
    fetch_limit: int = 50
    subject_keywords: list[str] = field(default_factory=list)

    # AI(OpenAI 兼容接口)
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "qwen-plus"
    llm_vision_model: str = ""          # 留空则复用 llm_model
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2048
    min_confidence: float = 0.6
    ai_timeout: int = 60
    max_retries: int = 3

    @property
    def vision_model(self) -> str:
        return self.llm_vision_model or self.llm_model

    # 下载
    download_timeout: int = 20
    download_max_bytes: int = 20 * 1024 * 1024

    # 路径
    db_file: Path = Path("data/fapiao.db")
    archive_dir: Path = Path("data/archive")
    output_file: Path = Path("data/output/发票汇总.xlsx")

    def ensure_dirs(self) -> None:
        """确保运行所需目录存在。"""
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.output_file.parent.mkdir(parents=True, exist_ok=True)


def load_config(config_path: str | Path = "config.yaml") -> Config:
    """读取 config.yaml(含账号/密钥),返回 Config。"""
    p = Path(config_path)
    if not p.exists():
        raise FileNotFoundError(
            f"找不到配置文件 {p}。请先 `cp config.example.yaml config.yaml` 再填写邮箱授权码与 API Key。"
        )
    raw: dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    imap = raw.get("imap", {})
    ai = raw.get("ai", {})
    download = raw.get("download", {})
    paths = raw.get("paths", {})

    data_dir = Path(paths.get("data_dir", "data"))
    db_file = Path(paths.get("db_file", data_dir / "fapiao.db"))
    archive_dir = Path(paths.get("archive_dir", data_dir / "archive"))
    output_file = Path(paths.get("output_file", data_dir / "output" / "发票汇总.xlsx"))

    return Config(
        imap_host=imap.get("host", ""),
        imap_port=int(imap.get("port", 993)),
        imap_user=imap.get("user", ""),
        imap_password=str(imap.get("password", "") or ""),
        imap_folder=imap.get("folder", "INBOX"),
        fetch_limit=int(imap.get("fetch_limit", 50)),
        subject_keywords=list(imap.get("subject_keywords", []) or []),
        llm_api_key=str(ai.get("api_key", "") or ""),
        llm_base_url=ai.get("base_url", ""),
        llm_model=ai.get("model", "qwen-plus"),
        llm_vision_model=ai.get("vision_model", "") or "",
        llm_temperature=float(ai.get("temperature", 0.1)),
        llm_max_tokens=int(ai.get("max_tokens", 2048)),
        min_confidence=float(ai.get("min_confidence", 0.6)),
        ai_timeout=int(ai.get("timeout", 60)),
        max_retries=int(ai.get("max_retries", 3)),
        download_timeout=int(download.get("timeout", 20)),
        download_max_bytes=int(download.get("max_bytes", 20 * 1024 * 1024)),
        db_file=db_file,
        archive_dir=archive_dir,
        output_file=output_file,
    )
