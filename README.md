# 🧾 FapiaoAutoFlow

**邮箱里的发票,自动变成一张报销 Excel。**

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![AI](https://img.shields.io/badge/AI-OpenAI%20兼容-green)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED)

商家把电子发票发到你邮箱,这个工具自动收件、用 AI 认出发票、提取全部字段、去重归档,
再汇总成一张 Excel —— 你只管定期打开核对、报销。

## 痛点

报销时,发票散落在几十封邮件里:有的是 PDF 附件,有的藏在正文链接或二维码后面,还有 OFD、图片……
手动一封封找、下载、抄金额、整理 Excel,既慢又容易漏。

## ✨ 特性

- 📬 **自动收件** —— IMAP 增量拉取,QQ / 163 等邮箱填授权码即可
- 🤖 **AI 识别全字段** —— 发票号、日期、金额、税额、买卖双方、消费明细,一次提取
- 🧩 **多来源覆盖** —— PDF / OFD / 图片附件、正文文本、下载直链,以及**二维码里的链接**
- 🗂️ **自动归档 + 去重** —— 原件按 `年/月` 存好;发票号唯一,重复邮件不重复入库
- 📁 **邮箱归类** —— 处理后把发票邮件移入「发票已处理 / 发票待处理」文件夹,邮箱即备份,可一键重建
- 📊 **一张 Excel** —— `发票汇总` + `待处理` 两个 sheet,打开即用
- ♻️ **幂等可常驻** —— cron / Docker 定时跑,重复运行不重复扣 API
- 🛟 **兜底不丢单** —— 认不出的进「待处理」清单,提醒你手动补录

## 🎯 效果

一封带 PDF 发票的邮件进来,自动变成汇总表里的一行(示例数据):

| 开票日期 | 发票号码 | 发票类型 | 销售方 | 金额 | 税额 | 价税合计 | 状态 |
|---|---|---|---|---|---|---|---|
| 2026-06-12 | 2631…45098 | 电子普通发票 | 某某餐饮有限公司 | 971.70 | 58.30 | 1030.00 | 已识别 |

原件同时归档到 `data/archive/2026/06/<发票号>.pdf`,随时溯源。

## 🧩 能处理的发票来源

1. **附件** —— PDF / OFD / 图片(zip 压缩包自动解开一层)
2. **正文下载链接** —— 直链文件自动下载识别
3. **二维码** —— 解码正文 / 图片里的二维码,取出链接再下载
4. **正文文本** —— 发票信息直接写在邮件正文里

> 需要登录或 JS 渲染的第三方开票平台链接(百望 / 航信等)统一进「待处理」清单 —— 这是有意为之,
> 避免为不可控的第三方平台过度投入。多数商家直发 PDF 附件,可稳定自动处理。

## 🏗️ 架构

模块化流水线,SQLite 为唯一事实来源,**全程幂等**(已处理邮件按 UID 跳过,发票按发票号去重):

```
收件 → 来源提取 → 归一化 → AI识别 → 去重入库+归档 → 导出 Excel
ingest  acquire   normalize  extract      store          export
```

- PDF 有文字层走**文本模型**(更准更省),图片 / 扫描件走**视觉模型**
- AI 走 **OpenAI 兼容接口** —— 通义千问 / 智谱等随意切换,只改 `config.yaml`

## 🚀 快速开始

一行装好,然后跟着向导填两三个问题即可:

```bash
curl -fsSL https://raw.githubusercontent.com/wangshub/FapiaoAutoFlow/main/install.sh | bash
```

它会克隆项目、建好虚拟环境装依赖,并运行配置向导(问你邮箱、授权码、AI key,自动生成 `config.yaml`)。装完:

```bash
cd ~/FapiaoAutoFlow
.venv/bin/fapiao run        # 收件 → 识别 → 入库 → 导出 Excel
```

> **邮箱授权码**(不是登录密码):邮箱设置 → 开启 IMAP/SMTP 服务 → 生成客户端授权码。
> 向导只问最关键的几项,其余都有合理默认;想细调见 `config.example.yaml`(每个字段都有注释)。

常用命令(激活 venv 后可直接用 `fapiao`):

```bash
fapiao init       # 重新配置(交互式生成 config.yaml)
fapiao run        # 收件并识别、入库、导出
fapiao export     # 仅根据现有数据重新生成 Excel
fapiao rebuild    # 灾难恢复:从邮箱归档文件夹重建本地数据
```

产出:汇总表 `data/output/发票汇总.xlsx`、原件归档 `data/archive/年/月/`、数据库 `data/fapiao.db`。

<details>
<summary>手动安装(不想用脚本)</summary>

```bash
git clone https://github.com/wangshub/FapiaoAutoFlow.git && cd FapiaoAutoFlow
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m fapiao init       # 或 cp config.example.yaml config.yaml 自行编辑
```
</details>

## 🐳 部署到 NAS / 服务器

Docker 一行启动,容器内每 30 分钟自动收一次(改 `RUN_INTERVAL` 调整,单位秒,默认 1800):

```bash
cp config.example.yaml config.yaml   # 先填好凭据
docker compose up -d --build
docker compose logs -f fapiao
```

数据卷挂在宿主机,容器重建 / 升级都不丢。不用 Docker 也可以直接 cron:

```cron
*/30 * * * * cd /path/to/FapiaoAutoFlow && .venv/bin/fapiao run >> data/cron.log 2>&1
```

## 📁 邮件归类与恢复

处理后,**有发票来源**的邮件会按结果移入文件夹(营销邮件留在收件箱不动):

| 结果 | 移入文件夹 |
|---|---|
| 成功识别出发票(或已入库的重复) | `发票已处理` |
| 有**发票附件 / 正文发票文本**但没识别成功(需人工) | `发票待处理` |
| 营销邮件等无发票信号 | 不动,留在收件箱 |

> 判定「发票相关」以**附件 / 正文发票文本**为准,避免营销邮件里能下载文件的链接被误判。
> 纯靠正文链接 / 二维码且未识别成功的邮件会留在收件箱,需你手动处理。

在 `config.yaml` 的 `imap` 段可关闭或改名(`organize` / `folder_done` / `folder_pending`)。

**邮箱就是异地备份。** 移动 ≠ 删除,原件连同附件都还在邮箱里。万一本地数据库 / 归档 / Excel 全丢,
一条命令从邮箱重建(遍历收件箱 + 两个归档文件夹,按发票号去重,可安全重复执行):

```bash
python -m fapiao rebuild
```

> 数据可靠性三层:**邮箱文件夹(最终事实来源)** → SQLite + 归档(`rebuild` 重建)→ Excel(`export` 重生成)。

## 🧪 测试

```bash
pip install pytest && pytest
```

单元测试覆盖各阶段(来源提取、归一化、识别解析、去重、导出),集成测试用假的下载器 / 二维码 / AI
跑通整条流水线 —— **不触网、不调真实 API**。

## 🔒 隐私与安全

- 🔑 **密钥只在本地** —— `config.yaml`(含邮箱授权码、API Key)已被 `.gitignore` 忽略,不会进 git
- 🏠 **数据只存本地** —— 发票原件、数据库、Excel 全在你自己的机器 / NAS 上,不上传任何云端
- 🤖 **识别会调用 AI** —— 发票内容会发送给你在 `config.yaml` 里配置的 AI 接口做识别,请选你信任的厂商

## 📂 目录结构

```
src/fapiao/
  ingest.py     IMAP 收件 + 邮件解析
  acquire.py    多来源发票提取(附件 / 链接 / 二维码 / 正文)
  normalize.py  PDF / OFD / 图片 → 模型可读输入
  extract.py    AI 识别 → 结构化 JSON
  store.py      SQLite 去重入库 + 文件归档
  export.py     生成 Excel
  pipeline.py   串联各阶段
  config.py     配置加载(config.yaml)
```
