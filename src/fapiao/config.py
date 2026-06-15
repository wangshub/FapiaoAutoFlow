"""配置加载:非敏感项来自 config.yaml,账号/密钥来自 .env(环境变量)。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


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
    """读取 .env + config.yaml,返回 Config。

    缺失的 IMAP/DashScope 凭据不会在此报错(便于测试),
    真正使用时再由各模块校验。
    """
    load_dotenv()

    raw: dict[str, Any] = {}
    p = Path(config_path)
    if p.exists():
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    imap = raw.get("imap", {})
    ai = raw.get("ai", {})
    download = raw.get("download", {})
    paths = raw.get("paths", {})

    data_dir = Path(paths.get("data_dir", "data"))
    db_file = Path(paths.get("db_file", data_dir / "fapiao.db"))
    archive_dir = Path(paths.get("archive_dir", data_dir / "archive"))
    output_file = Path(paths.get("output_file", data_dir / "output" / "发票汇总.xlsx"))

    return Config(
        imap_host=os.getenv("IMAP_HOST", ""),
        imap_port=int(os.getenv("IMAP_PORT", "993")),
        imap_user=os.getenv("IMAP_USER", ""),
        imap_password=os.getenv("IMAP_PASSWORD", ""),
        imap_folder=imap.get("folder", "INBOX"),
        fetch_limit=int(imap.get("fetch_limit", 50)),
        subject_keywords=list(imap.get("subject_keywords", []) or []),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_base_url=os.getenv("LLM_BASE_URL", ""),
        llm_model=os.getenv("LLM_MODEL", "") or ai.get("model", "qwen-plus"),
        llm_vision_model=os.getenv("LLM_VISION_MODEL", "") or ai.get("vision_model", ""),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "") or ai.get("temperature", 0.1)),
        llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "") or ai.get("max_tokens", 2048)),
        min_confidence=float(ai.get("min_confidence", 0.6)),
        ai_timeout=int(ai.get("timeout", 60)),
        max_retries=int(ai.get("max_retries", 3)),
        download_timeout=int(download.get("timeout", 20)),
        download_max_bytes=int(download.get("max_bytes", 20 * 1024 * 1024)),
        db_file=db_file,
        archive_dir=archive_dir,
        output_file=output_file,
    )
