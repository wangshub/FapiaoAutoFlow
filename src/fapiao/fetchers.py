"""默认的下载器与二维码解码器(有副作用:联网 / 用 opencv)。

acquire.py 通过参数注入这两个函数,所以单元测试时可以用假实现替换。
"""

from __future__ import annotations

from typing import Optional


def make_downloader(timeout: int = 20, max_bytes: int = 20 * 1024 * 1024):
    """返回一个下载函数:url -> (data, content_type) 或 None。"""
    import requests

    def download(url: str) -> Optional[tuple[bytes, str]]:
        try:
            resp = requests.get(url, timeout=timeout, stream=True, allow_redirects=True)
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            resp.close()
            return None

        content_type = resp.headers.get("Content-Type", "")
        chunks = []
        total = 0
        for chunk in resp.iter_content(8192):
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                resp.close()
                return None
        resp.close()
        return b"".join(chunks), content_type

    return download


def decode_qr(image_bytes: bytes) -> list[str]:
    """用 opencv 自带的 QRCodeDetector 解码图片里的二维码,返回内容字符串列表。

    免装 zbar 系统库。解不出返回空列表。
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return []

    detector = cv2.QRCodeDetector()
    results: list[str] = []
    try:
        ok, decoded, _points, _ = detector.detectAndDecodeMulti(img)
        if ok:
            results.extend([d for d in decoded if d])
    except cv2.error:
        pass

    if not results:
        # 退而求其次:单个二维码
        try:
            data, _points, _ = detector.detectAndDecode(img)
            if data:
                results.append(data)
        except cv2.error:
            pass

    return results
