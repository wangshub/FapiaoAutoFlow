"""AI 识别:调通义千问,按固定 JSON Schema 提取发票全字段。

  - build_prompt / parse_response / record_from_data 是纯函数,易测试
  - _call_text / _call_vision 封装 DashScope 调用,可在测试中替换
"""

from __future__ import annotations

import base64
import json
import re
import time
from typing import Any, Callable, Optional

from .models import (
    MODE_IMAGE,
    MODE_TEXT,
    STATUS_OK,
    InvoiceRecord,
    NormalizedInput,
)

# 要求模型输出的字段
FIELDS = [
    "发票号码", "发票代码", "开票日期", "发票类型",
    "销售方名称", "销售方税号", "购买方名称", "购买方税号",
    "金额", "税率", "税额", "价税合计", "消费明细", "备注",
]

PROMPT = """你是一个中国增值税发票信息提取助手。请从下面的发票内容中提取信息,只输出一个 JSON 对象,不要有任何额外文字或解释。

JSON 字段说明:
- 发票号码: 字符串
- 发票代码: 字符串(数电票可能没有,填空字符串)
- 开票日期: 字符串,统一格式 YYYY-MM-DD
- 发票类型: 如「电子普通发票」「电子专用发票」「数电普通发票」等
- 销售方名称 / 销售方税号: 字符串
- 购买方名称 / 购买方税号: 字符串
- 金额: 数字,不含税金额(合计金额)
- 税率: 字符串,如「6%」「免税」
- 税额: 数字
- 价税合计: 数字(含税总额)
- 消费明细: 数组,每个元素 {"名称":..., "金额":数字, "税率":..., "税额":数字}
- 备注: 字符串
另外附加两个字段:
- is_invoice: 布尔,内容是否确实是一张发票
- confidence: 0~1 的数字,你对本次提取整体准确度的置信

找不到的字段填空字符串或 null。只输出 JSON。"""


class ExtractError(Exception):
    """识别失败(API 错误 / 无法解析 / 不是发票),应记入待处理。"""


def build_prompt(invoice_text: str = "") -> str:
    if invoice_text:
        return PROMPT + "\n\n发票内容如下:\n" + invoice_text
    return PROMPT


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[^\d.\-]", "", str(value))
    try:
        return float(s) if s else None
    except ValueError:
        return None


def parse_response(raw: str) -> dict[str, Any]:
    """从模型输出里抽出 JSON 对象。失败抛 ExtractError。"""
    if not raw:
        raise ExtractError("模型返回为空")
    text = raw.strip()
    # 去掉 ```json ... ``` 围栏
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        # 取第一个 { 到最后一个 }
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ExtractError(f"模型输出非合法 JSON:{e}")


def record_from_data(data: dict[str, Any], normalized: NormalizedInput,
                     uid: int, raw: str) -> InvoiceRecord:
    """把解析出的 dict 映射为 InvoiceRecord。"""
    明细 = data.get("消费明细") or []
    if not isinstance(明细, list):
        明细 = []
    return InvoiceRecord(
        发票号码=str(data.get("发票号码") or "").strip(),
        发票代码=str(data.get("发票代码") or "").strip(),
        开票日期=str(data.get("开票日期") or "").strip(),
        发票类型=str(data.get("发票类型") or "").strip(),
        销售方名称=str(data.get("销售方名称") or "").strip(),
        销售方税号=str(data.get("销售方税号") or "").strip(),
        购买方名称=str(data.get("购买方名称") or "").strip(),
        购买方税号=str(data.get("购买方税号") or "").strip(),
        金额=_to_float(data.get("金额")),
        税率=str(data.get("税率") or "").strip(),
        税额=_to_float(data.get("税额")),
        价税合计=_to_float(data.get("价税合计")),
        消费明细=明细,
        备注=str(data.get("备注") or "").strip(),
        confidence=float(_to_float(data.get("confidence")) or 0.0),
        source_email_uid=uid,
        source_origin=normalized.source.origin if normalized.source else "",
        status=STATUS_OK,
        raw_json=raw,
    )


# ---------------- DashScope 调用 ----------------

def _retry(fn: Callable[[], str], max_retries: int) -> str:
    last = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(min(2 ** attempt, 8))
    raise ExtractError(f"AI 调用失败(重试 {max_retries} 次):{last}")


def _client(config):
    from openai import OpenAI

    return OpenAI(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url or None,
        timeout=config.ai_timeout,
    )


def _chat(config, model: str, content) -> str:
    client = _client(config)

    def once() -> str:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            temperature=config.llm_temperature,
            max_tokens=config.llm_max_tokens,
        )
        return resp.choices[0].message.content or ""

    return _retry(once, config.max_retries)


def _call_text(text: str, config) -> str:
    return _chat(config, config.llm_model, build_prompt(text))


def _call_vision(images: list[bytes], config) -> str:
    content: list[dict[str, Any]] = [{"type": "text", "text": build_prompt()}]
    for img in images:
        b64 = base64.b64encode(img).decode()
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"}})
    return _chat(config, config.vision_model, content)


def extract_invoice(normalized: NormalizedInput, config, uid: int = 0,
                    text_fn: Callable = _call_text,
                    vision_fn: Callable = _call_vision) -> InvoiceRecord:
    """识别一张发票。失败/非发票抛 ExtractError。低置信度由 pipeline 判定。"""
    if normalized.mode == MODE_TEXT:
        raw = text_fn(normalized.text, config)
    elif normalized.mode == MODE_IMAGE:
        raw = vision_fn(normalized.images, config)
    else:
        raise ExtractError(f"未知输入模式:{normalized.mode}")

    data = parse_response(raw)
    if data.get("is_invoice") is False:
        raise ExtractError("模型判定内容不是发票")

    record = record_from_data(data, normalized, uid, raw)
    if not record.发票号码:
        raise ExtractError("未能提取到发票号码")
    return record
