# FapiaoAutoFlow 部署镜像(目标平台 x86_64 / linux-amd64)
FROM python:3.12-slim

# 时区 + 国内 pip 源;libgl1/libglib2.0-0 供 opencv / easyofd(OFD)渲染所需
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    RUN_INTERVAL=1800

RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata libgl1 libglib2.0-0 \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖,利用 Docker 层缓存(只改源码时不必重装依赖)
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt \
    && pip install --no-cache-dir --prefer-binary easyofd   # OFD 国标电子发票支持

# 再拷源码并安装本包;config.example.yaml 作为镜像内默认配置
COPY src ./src
COPY README.md ./
COPY config.example.yaml ./config.yaml
RUN pip install --no-cache-dir .

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# 运行数据目录(部署时被 NAS 卷覆盖)
RUN mkdir -p /app/data

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
