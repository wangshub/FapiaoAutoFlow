# FapiaoAutoFlow · 发票邮件自动识别归档

自动从邮箱收取邮件,用 AI(通义千问)识别邮件正文/附件里的增值税发票,提取全字段,
**去重汇总成 Excel 并归档原始文件**,处理不了的进「待处理」清单等你手动补录。
专为「商家把电子发票发到邮箱、需要定期整理报销」的场景设计。

## 能处理的发票来源

1. **附件**:PDF / OFD / 图片(zip 压缩包会自动解开一层)
2. **正文下载链接**:直链文件自动下载识别
3. **二维码**:解码正文/图片里的二维码,取出链接再下载
4. **正文文本**:发票信息直接写在邮件正文里

> 需要登录或 JS 渲染的第三方开票平台链接(百望/航信等)目前一律进「待处理」清单——
> 这是有意为之,避免为不可控的第三方平台过度投入。多数商家直接发 PDF 附件,可稳定自动处理。

## 架构

模块化流水线 + SQLite 状态库,**幂等可重复执行**(已处理邮件按 UID 跳过,发票按发票号去重):

```
收件 → 来源提取 → 归一化 → AI识别 → 去重入库+归档 → 导出Excel
ingest  acquire   normalize  extract     store        export
```

- PDF 有文字层走文本模型 `qwen-plus`(更准更省);图片/无文字层走视觉模型 `qwen-vl-max`
- SQLite 是唯一事实来源;Excel 只是导出视图(`发票汇总` + `待处理` 两张表)
- 原始发票按 `data/archive/年/月/<发票号>.<ext>` 归档

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 配置

```bash
cp .env.example .env            # 填邮箱授权码、DashScope API Key
cp config.example.yaml config.yaml
```

- **邮箱授权码**(不是登录密码):
  - QQ:设置 → 账户 → 开启 IMAP/SMTP → 生成授权码
  - 163:设置 → POP3/SMTP/IMAP → 开启 IMAP → 授权码
- **DashScope API Key**:<https://dashscope.console.aliyun.com/>

## 使用

```bash
python -m fapiao run        # 收件 → 识别 → 入库 → 导出 Excel
python -m fapiao export     # 仅根据现有数据重新生成 Excel
python -m fapiao -v run     # 详细日志
```

结果:
- 汇总表:`data/output/发票汇总.xlsx`
- 原始发票:`data/archive/2026/06/...`
- 数据库:`data/fapiao.db`

## 定时运行(云服务器 / NAS)

用 cron 每 30 分钟跑一次:

```cron
*/30 * * * * cd /path/to/FapiaoAutoFlow && .venv/bin/python -m fapiao run >> data/cron.log 2>&1
```

## 测试

```bash
pip install pytest
pytest
```

单元测试覆盖各阶段(来源提取、归一化、识别解析、去重、导出),
集成测试用假的下载器/二维码/AI 跑通整条 pipeline,均不触网、不调真实 API。

## 目录结构

```
src/fapiao/
  config.py     配置加载(.env + config.yaml)
  models.py     阶段间数据结构
  ingest.py     IMAP 收件 + 邮件解析
  acquire.py    多来源发票提取(附件/链接/二维码/正文)
  fetchers.py   默认下载器 + 二维码解码(opencv)
  normalize.py  PDF/OFD/图片 → 模型可读输入
  extract.py    通义千问识别 → 结构化 JSON
  store.py      SQLite 去重入库 + 文件归档
  export.py     生成 Excel
  pipeline.py   串联各阶段
  cli.py        命令行入口
tests/          单元 + 集成测试
```
