# OPGD CLI

[![CI](https://github.com/seedgcoding/OPGD_CLI/actions/workflows/ci.yml/badge.svg)](https://github.com/seedgcoding/OPGD_CLI/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/badge/PyPI-opgd--cli-blue)](https://pypi.org/project/opgd-cli/)

[OPGD 平台（基于最优参数的地理探测器）](https://opgd500.kkbvip.top) 的命令行客户端 —— 在终端完成 **上传数据 → 提交分析 → 查看报告 → 导出结果** 全流程。

**OPGD**（Optimal Parameters-based Geographical Detector，基于最优参数的地理探测器）是地理探测器（Geodetector）的增强算法（Song et al., 2020）：遍历离散化方法与分级数组合自动寻优，克服传统 Geodetector 人为分级的主观性。

纯 HTTP 客户端实现，不依赖平台代码，兼容任意自部署实例（`--server` 指定地址即可）。

## AI Agent 使用指南

如果你是 AI Agent（Claude / ChatGPT / Cursor / ZCode 等）在协助用户使用本工具，请严格按以下决策树操作：

**第 1 步 · 安装与自检**

```bash
pip install opgd-cli        # 要求 Python 3.10+
opgd doctor                 # 环境自检：全部 ✔ 才继续；✗ 项按"详情"列提示处理
```

**第 2 步 · 按场景选通道**

```bash
# 场景 A：用户无账号 / 只想快速验证 → 免登录试用（开箱即用）
opgd trial 数据.csv -y 因变量 -x 自变量1,自变量2 --cat 分类变量   # 无文本列则省略 --cat

# 场景 B：需要完整报告/导出/历史任务 → 正式通道（需账号）
echo '密码' | opgd auth login -u 账号 --password-stdin
opgd analyze 数据.csv -y 因变量 -x 自变量1,自变量2 --cat 分类变量
opgd export <task_id> -o ./结果 --unzip --png
```

**第 3 步 · 结果解析**

- 供程序/Agent 消费时一律加 `--json`，其余输出仅供人类阅读
- q 值（0~1）越大解释力越强；交互类型见 `opgd analyze --help`

**退出码语义**（按码决策，不要盲目重试）：

| 退出码 | 含义 | 应对 |
|--------|------|------|
| 0 | 成功 | — |
| 2 | 服务端错误/网络不通 | 重试一次；仍失败跑 `opgd doctor` |
| 3 | 登录过期/凭据错误 | 重新 `opgd auth login` |
| 4 | 额度不足 | 告知用户，勿重试 |
| 5 | 触发限流 | 等待 10~60 秒后重试 |
| 6 | 任务失败 | 向用户转述错误详情 |
| 7 | 未登录 | 先 `opgd auth login` |

**硬性行为约束**（违反会产生错误结果）：

1. 上传文件**一次性**：同一文件第二次分析请直接传文件路径，不要复用 `--upload-id`
2. 文本/分类列**必须** `--cat` 声明，否则服务端按数值处理导致有效样本清零
3. 登录 token 有效期 30 分钟，过期退出码为 3
4. 免费通道限流约 5 次分析/分钟/IP，收到 429 属正常保护

## 安装

```bash
pip install opgd-cli
```

要求 Python 3.10+。开发者安装：`pip install -e ".[dev]"`。

## 快速开始

### 免登录试用（零配置）

```bash
opgd trial data.csv -y GDP -x X1 X2 X3
```

免费试用通道无需账号，秒级返回因子探测器 q 值结果。

### 登录正式通道（完整报告）

```bash
opgd login
opgd analyze data.csv -y GDP -x X1 X2 --cat X3 --bins 3:8 --methods quantile,natural_breaks
opgd report <task_id>          # 终端渲染四探测器结果
opgd export <task_id> -o ./结果 --unzip --png
```

## 命令一览

| 命令 | 说明 |
|------|------|
| `opgd trial <file>` | 免登录试用：上传 → 同步分析 → 因子探测结果 |
| `opgd login` / `opgd logout` | 登录管理（凭据存于 `~/.opgd/config.toml`） |
| `opgd whoami` | 账号信息（角色/剩余次数/已用次数/状态） |
| `opgd doctor` | 环境自检：连通性 / 登录态 / 额度 |
| `opgd upload <file>` | 上传数据，展示列元数据与服务端角色推荐 |
| `opgd analyze <file>` | 正式通道一条龙：提交 → 轮询 → 渲染完整报告 |
| `opgd status <task_id>` | 查询任务状态 |
| `opgd wait <task_id>` | 等待任务完成并渲染报告 |
| `opgd tasks` | 历史任务列表 |
| `opgd cancel <task_id>` | 取消任务 |
| `opgd report <task_id>` | 终端渲染完整报告 |
| `opgd export <task_id> -o <dir>` | 下载报告 ZIP（`--unzip` 解压，`--png` 附带图表） |

## analyze 参数

| 参数 | 说明 |
|------|------|
| `-y / --y` | 因变量列名 |
| `-x / --x` | 自变量列名（可多次或逗号分隔） |
| `-c / --cat` | 类型变量（须来自 -x） |
| `-m / --methods` | 离散化方法：`equal_interval` `quantile` `natural_breaks` `geometric` `std_mean`（fuzzygd 另有 `kmeans` `rgd`） |
| `-b / --bins` | 分级数范围，如 `3:8` |
| `--model` | `opgd` / `fuzzygd`（模糊地理探测器） |
| `--fuzziness` | 模糊系数模式：`quick` / `fine` / `custom` |
| `--fz-values` | 自定义模糊系数，如 `1,2,3` |
| `--perm` | 置换检验次数（0~5000） |
| `--upload-id` | 复用已上传文件（**一次性**，见下方说明） |
| `--no-wait` | 只提交不等待 |
| `--json` | 原始 JSON 输出（脚本友好） |

## 重要使用说明（源自线上平台行为）

1. **上传文件是一次性的**：平台在分析任务结束后会删除服务端的 uploaded 文件，同一 `upload_id` 只能分析一次。分析第二次请直接用文件路径重新上传（CLI 会自动重新上传）。用 `--upload-id` 复用已消费的文件时，CLI 会给出明确提示。
2. **分类变量必须显式声明**：`X3` 这类文本型变量要传 `--cat X3`，否则服务端按数值处理会导致有效样本清零（报"有效数据不足"）。CLI 会在上传后自动检测疑似分类变量并提醒。
3. **失败自动退款**：任务失败会自动返还分析次数（token ledger 记账）。
4. **登录 token 有效期 30 分钟**（服务端策略）：过期后任意正式通道命令会提示重新 `opgd login`。
5. **登录**：`opgd login` 支持交互输入；脚本/CI 用 `echo 密码 | opgd login -u 账号 --password-stdin`。
6. **试用通道不支持自定义方法/分级数**：服务端自动寻优（`trial` 的参数只有文件、-y、-x、--cat）。

## 自部署实例

```bash
opgd --server https://my-opgd.example.com login
# 或环境变量
export OPGD_SERVER=https://my-opgd.example.com
```

## 网络与代理

- 开启系统代理（如 Clash）时，若代理节点无法访问服务端，CLI 会**自动改用直连重试**并给出提示
- 固定直连（跳过一切系统代理）：

```bash
export OPGD_NO_PROXY=1
```

- 指定服务端地址：`--server` 参数 > `OPGD_SERVER` 环境变量 > `~/.opgd/config.toml`

## 故障排查

| 现象 | 处理 |
|------|------|
| `[401] token 失效` | 重新 `opgd login` |
| `[429] 触发服务端限流` | 按提示等待后重试；免费通道有次数限制 |
| `额度不足` | 登录正式账号，或联系平台管理员 |
| SSL/连接错误且自动直连仍失败 | 检查网络/防火墙；确认服务端地址可达 |

## 开发

```bash
pip install -e ".[dev]"
pytest                # 50 个测试：单元（respx 模拟）+ 本地全链路 E2E
```

### 本地模拟测试（不碰生产环境）

`tests/mock_server.py` 是一个本地 OPGD 模拟服务，复刻线上行为契约
（异步任务生命周期、一次性上传、额度扣减、401/402/429），可与 CLI 跑完整闭环：

```bash
python tests/mock_server.py --port 8092 --tokens 5
# 另开终端：
export OPGD_NO_PROXY=1   # 本地回环务必绕过系统代理
opgd --server http://127.0.0.1:8092 auth login -u tester --password-stdin
opgd --server http://127.0.0.1:8092 analyze examples/sample_data.csv -y GDP -x X1,X2
```

`pytest` 中的 `tests/test_e2e_local.py` 会自动起停该服务并覆盖 8 条端到端链路。

## License

MIT
