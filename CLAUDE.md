# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FapiaoAutoFlow 自动从 QQ/163 邮箱(IMAP)收件,用 AI 识别邮件正文或附件中的中国增值税电子发票,提取全字段、去重入库、归档原始文件,并导出 Excel 汇总,供定期报销核对。常驻云服务器/NAS,由 cron 定时触发;整条流程**幂等**(重复运行不重复入库、不重复扣 API)。

## Commands

```bash
# 安装(src-layout,可编辑安装)。中国网络下走阿里镜像更稳:
pip install -e . --index-url https://mirrors.aliyun.com/pypi/simple/

# 运行一整轮:收件 → 识别 → 入库 → 导出 Excel
python -m fapiao run            # 默认读 config.yaml
python -m fapiao -v run         # 详细日志
python -m fapiao -c other.yaml run

# 仅根据现有 SQLite 数据重新生成 Excel(不收件、不调 API)
python -m fapiao export

# 灾难恢复:本地数据丢失后从邮箱(含归档文件夹)重建 SQLite+归档+Excel
python -m fapiao rebuild

# 测试(pytest 配置在 pyproject.toml,已把 src/ 加入 pythonpath)
pytest                          # 全部
pytest tests/test_pipeline.py   # 单文件
pytest tests/test_store.py::test_archive_path_uses_year_month   # 单用例
```

注意:本机 Bash sandbox 会把网络限速到极低,任何联网命令(pip/真实联调)需带 `dangerouslyDisableSandbox=true`。已知 pip 摩擦点见 git 历史 — 用 `PIP_CONFIG_FILE=/dev/null` 绕过全局 pip.conf 的失效镜像,网络抖动时逐包安装 `--timeout 300 --retries 20 --prefer-binary`。

## Configuration

**单一配置文件 `config.yaml`(含账号/密钥),已 gitignore,绝不提交**。提交的只有占位符模板 `config.example.yaml`。`load_config()` 只读 yaml(无 `.env`/环境变量),文件缺失直接抛 `FileNotFoundError`。

- `imap` 段 — `host/port/user/password`(163 用授权码,非登录密码)、`folder/fetch_limit/subject_keywords`。
- `ai` 段 — `api_key/base_url/model/vision_model/temperature/max_tokens` + `min_confidence/timeout/max_retries`。
- `download`、`paths` 段 — 下载限制与数据目录。

AI 用的是 **OpenAI 兼容接口**(`openai` 包,非 dashscope 原生 SDK),换任何兼容厂商只改 `ai.base_url/model`。`config.py` 里 `vision_model` 留空则复用 `llm_model`。

## Architecture

模块化流水线,**SQLite 是唯一事实来源**(`data/fapiao.db`),Excel 只是导出视图。各阶段在 `src/fapiao/`:

```
ingest → acquire → normalize → extract → store → export
(IMAP)  (附件/链接/二维码) (PDF/OFD/图→统一) (LLM JSON) (SQLite+归档) (Excel)
```

1. **`ingest.py`** — `MailReader` 连 IMAP 增量拉未处理邮件;`parse_email(uid, raw_bytes)` 是纯函数(可脱离 IMAP 测试),拆出附件/内嵌图/正文。
2. **`acquire.py`** — `acquire_sources(em, downloader, qr_decoder)` 按优先级产出发票来源:**附件(含 zip 递归)→ 正文下载直链 → 二维码解码后的链接 → 正文纯文本**。下载到登录墙/JS 页面、链接失效、二维码解不出 → 记 pending。
3. **`normalize.py`** — 把来源转成喂模型的 `NormalizedInput`:PDF 先用 pdfplumber 抽文字层,`text_is_sufficient` 则走文本模式,否则 PyMuPDF(fitz)渲染成图走视觉模式;图片直接视觉;OFD 用 easyofd(可选依赖,缺失则抛 `NormalizeError` → pending)。
4. **`extract.py`** — 调 LLM(`_call_text`/`_call_vision`),强制输出固定字段 JSON,带超时+重试;`parse_response` 容忍 ```json 围栏。缺 `发票号码` 或判定非发票 → `ExtractError`。
5. **`store.py`** — `Store`(SQLite)。三表:`processed_emails`(邮件 UID 去重,省 API)、`invoices`(**`发票号码` 为主键去重**)、`pending`。`archive_file` 把原件写到 `archive_dir/YYYY/MM/<发票号>.<ext>`(年月来自 `_year_month` 解析开票日期的全部数字)。
6. **`export.py`** — openpyxl 生成两个 sheet:`发票汇总` + `待处理`。
7. **`pipeline.py`** — `process_email(...)` 是核心、**不依赖 IMAP**(便于测试);`run(config)` 串起全流程。低置信度 → pending,而非丢弃。`_target_folder(part, config)` 是纯函数,决定处理后把邮件移入哪个文件夹(识别成功/重复→已处理;有「强发票信号」即附件或正文发票文本但失败→待处理;否则不移)。`Stats.strong_sources` 只数附件/压缩包/正文文本来源,**不数正文链接、二维码下载**——避免营销邮件里能下文件的链接被误判;判定靠 `acquire` 的 `source.origin` 前缀。移动用「延迟到收件结束后、新连接统一搬」(`_apply_moves`),规避 163 拉大邮件后掐断 socket 导致紧跟的 COPY 失败。`rebuild(config)` 用于灾难恢复:遍历 INBOX + 两个归档文件夹重新识别,**每文件夹独立连接**(163 在大邮件后会掐断 socket,重连避免拖垮其余文件夹),按发票号去重故可安全重复跑。
8. **`cli.py` / `__main__.py`** — argparse 入口。

### 设计约定

- **依赖注入做可测试性**:`process_email`/`run` 接收 `downloader`、`qr_decoder`、`extract_fn`,测试传 fake,不触网、不调真实 API。新增逻辑应延续这一点。
- **失败兜底而非抛弃**:任何阶段处理不了都进 `pending` 表(记主题/发件人/原因/链接),由用户手动补录;每封邮件独立 try/except,单封失败不阻塞其他。
- **幂等**靠两道去重:`processed_emails.uid` + `invoices.发票号码`。改动入库/归档逻辑时务必保持。
- **字段命名直接用中文**(`发票号码`、`价税合计` 等)贯穿 models/store/export,刻意保持以对齐发票语义 — 不要改成拼音/英文。
- **第三方开票平台需登录/JS 渲染的链接,Phase 1 一律进 pending**,这是有意为之,不要为不可控平台过度投入。

### 测试注意

PyMuPDF(fitz)用默认 Helvetica 字体**无法嵌入中文**,所以 PDF 文字层测试 fixture 用 ASCII(含关键词 `invoice`),配合 `text_is_sufficient` 的大小写不敏感匹配。不要在测试 PDF 里塞中文期望抽得出文字层。
