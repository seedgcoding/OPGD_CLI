---
name: opgd-geodetector
description: OPGD 最优参数地理探测器分析技能。当用户需要地理探测器分析（Geodetector）、空间分异分析、因子探测/交互探测/风险探测/生态探测、q 值统计、OPGD 分析、把栅格数据转成分析表格，或提到"地理探测器""geodetector""q值""空间分异""影响因素分析"时使用——即使用户没有明确说"地理探测器"这个词。通过 opgd-cli 命令行工具完成：CSV/Excel 上传、一行命令分析（免登录试用）、终端渲染四探测器报告、导出 ZIP/PNG。
---

# OPGD 地理探测器分析

通过 `opgd-cli` 命令行工具（纯 HTTP 客户端，Python 3.10+）完成地理探测器全流程分析。

## 第一步：确认工具可用

```bash
opgd --version 2>/dev/null || pip install opgd-cli
# pip 安装失败时的回退：
pip install git+https://github.com/seedgcoding/OPGD_CLI.git
```

然后运行自检：

```bash
opgd doctor
```

输出四项检查（配置/服务健康/登录态/额度）。全部 ✔ 继续；有 ✗ 按详情列提示处理（未登录不影响 trial 通道）。

## 第二步：选择通道

| 场景 | 用哪个 |
|------|--------|
| 用户没有账号 / 快速验证 / 只关心因子解释力 | `opgd trial`（**免登录**，只出因子探测 q 值） |
| 需要完整四探测器报告 / 导出 ZIP+PNG / 历史任务 | `opgd login` 后 `opgd analyze` |

## 第三步：运行分析

**免登录试用（优先推荐）：**

```bash
opgd trial 数据.csv -y 因变量列名 -x 自变量1,自变量2,自变量3
```

**正式通道（完整报告）：**

```bash
echo '密码' | opgd auth login -u 账号 --password-stdin
opgd analyze 数据.csv -y GDP -x X1,X2,X3 --cat X3
opgd export <task_id> -o ./结果 --unzip --png
```

供自己（Agent）解析结果时**一律加 `--json`**，人类阅读时不加。

完整命令参考（含全部参数、batch 选项）和结果解读指南，需要时再读取：

- `references/commands.md` —— 全部命令与参数速查
- `references/interpretation.md` —— 四探测器结果解读 + 论文句式模板

## 退出码语义（按码决策，不要盲目重试）

| 码 | 含义 | 应对 |
|----|------|------|
| 0 | 成功 | — |
| 2 | 服务端错误/网络不通 | 重试一次；仍失败跑 `opgd doctor` |
| 3 | 登录过期/凭据错误 | 重新 `opgd auth login`（token 有效期 30 分钟） |
| 4 | 额度不足 | 告知用户，勿重试 |
| 5 | 触发限流 | 等待 10~60 秒后重试 |
| 6 | 任务失败 | 向用户转述 stderr 中的服务端原因 |
| 7 | 未登录 | 走 trial 通道或引导用户 login |
| 130 | 用户中断等待 | 任务仍在服务端运行，可用 `opgd status` 查看 |

## 硬性约束（违反会产生错误结果）

1. **分类/文本列必须用 `--cat` 显式声明**，否则服务端按数值处理导致有效样本清零（报"有效数据不足"）。判断方法：上传响应里 `inferred_role` 为 categorical 或 `dtype` 为 object 的列。
2. **上传文件是一次性的**：任务结束后服务端删除文件。同一文件第二次分析请直接再传文件路径，不要复用 `--upload-id`。
3. 免费通道限流约 5 次分析/分钟/IP，429 是正常保护，收到后等待重试。
4. `-x` 传参格式：`-x A -x B` 或 `-x A,B`（逗号分隔），不支持空格分隔多个值。
5. Y 不能出现在 X 列表中；`--cat` 声明的列必须属于 X。
6. 上传文件 ≤ 50MB，支持 csv/xlsx/xls。

## 结果解读

分析完成后（或拿到 `--json` 输出后），读取 `references/interpretation.md` 向用户解释：
- q 值含义与主导因子判定
- 交互探测五种类型的人话解释
- 论文写作句式模板（用户是科研场景时主动提供）
