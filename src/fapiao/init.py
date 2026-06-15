"""交互式配置向导:问几个问题,生成 config.yaml,免得手写 YAML、对着字段手册填。"""

from __future__ import annotations

import getpass
from pathlib import Path

# 常见邮箱 → IMAP 服务器,自动带出,省得用户查
_KNOWN_IMAP = {
    "163.com": "imap.163.com",
    "126.com": "imap.126.com",
    "yeah.net": "imap.yeah.net",
    "qq.com": "imap.qq.com",
    "foxmail.com": "imap.qq.com",
    "gmail.com": "imap.gmail.com",
    "outlook.com": "outlook.office365.com",
    "hotmail.com": "outlook.office365.com",
}

_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_DEFAULT_MODEL = "qwen-plus"

_TEMPLATE = """# 本文件含真实凭据,已被 .gitignore 忽略,请勿提交。

imap:
  host: {host}
  port: 993
  user: {user}
  password: "{password}"   # IMAP 授权码,不是邮箱登录密码
  folder: INBOX
  fetch_limit: 50
  subject_keywords: []
  organize: true
  folder_done: 发票已处理
  folder_pending: 发票待处理

ai:
  api_key: "{api_key}"
  base_url: "{base_url}"
  model: {model}
  vision_model: {vision_model}
  temperature: 0.1
  max_tokens: 2048
  min_confidence: 0.6
  timeout: 60
  max_retries: 3

download:
  timeout: 20
  max_bytes: 20971520

paths:
  data_dir: data
  db_file: data/fapiao.db
  archive_dir: data/archive
  output_file: data/output/发票汇总.xlsx
"""


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"{prompt}{suffix}: ").strip() or default


def run_init(config_path: str = "config.yaml") -> int:
    """跑配置向导,把答案写进 config.yaml。返回退出码。"""
    p = Path(config_path)
    if p.exists() and _ask(f"{p} 已存在,覆盖?(y/N)", "N").lower() not in ("y", "yes"):
        print("已取消,保留原 config.yaml。")
        return 0

    print("\n== FapiaoAutoFlow 配置向导 ==")
    print("按提示填写,带 [默认值] 的直接回车即可。授权码 / key 输入时不显示。\n")

    user = _ask("邮箱地址(如 you@163.com)")
    domain = user.split("@")[-1].lower() if "@" in user else ""
    host = _KNOWN_IMAP.get(domain) or _ask("IMAP 服务器地址", f"imap.{domain}" if domain else "")
    password = getpass.getpass("IMAP 授权码(邮箱设置里开启 IMAP 后生成,非登录密码): ").strip()

    print("\nAI 识别 —— OpenAI 兼容接口(通义千问 / 智谱等都行):")
    api_key = getpass.getpass("  api_key: ").strip()
    base_url = _ask("  base_url", _DEFAULT_BASE_URL)
    model = _ask("  文本模型", _DEFAULT_MODEL)
    vision_model = _ask("  视觉模型(图片发票用;回车=同文本模型)", model)

    p.write_text(
        _TEMPLATE.format(
            host=host, user=user, password=password,
            api_key=api_key, base_url=base_url, model=model, vision_model=vision_model,
        ),
        encoding="utf-8",
    )
    print(f"\n✅ 已写入 {p}")
    print("   立即试跑:python -m fapiao run\n")
    return 0
