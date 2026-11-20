# OPGD CLI 命令参考

> 安装：`pip install opgd-cli`（Python 3.10+）· 回退：`pip install git+https://github.com/seedgcoding/OPGD_CLI.git`
> 服务地址：默认官方平台；自部署用 `--server` 或环境变量 `OPGD_SERVER`；`OPGD_NO_PROXY=1` 强制直连。

## 命令速查

### 免登录试用

```bash
opgd trial <file> -y <col> -x <cols> [--cat <cols>] [--json] [--server <url>]
```

- 同步分析（几秒返回），仅展示因子探测 q 值，其余模块被遮罩
- 离散化方法与分级数由服务端自动寻优，**不接受自定义参数**
- 有限流与规模限制（≤300 行数据自动截断时会提示）

### 认证

```bash
opgd auth login [-u <account>] [--password-stdin] [--server <url>]  # 登录，token 存 ~/.opgd/config.toml，30 分钟有效
opgd auth whoami [--json]   # 账号信息：角色/剩余次数/已用次数/状态
opgd auth logout            # 清除本地凭据
opgd doctor                 # 环境自检：配置/服务健康/登录态/额度
```

### 上传与正式分析

```bash
opgd upload <file> [--json]                 # 上传，返回 upload_id（一次性）与列推荐
opgd analyze [<file> | --upload-id N] -y <col> -x <cols> [选项]
opgd analyze 选项:
  --cat <cols>            类型变量（必须属于 -x）
  -m, --methods <list>    equal_interval,quantile,natural_breaks,geometric,std_mean（fuzzygd 另有 kmeans,rgd）
  -b, --bins MIN:MAX      分级数范围（2 ≤ MIN ≤ MAX ≤ 20，默认 3:8）
  --model opgd|fuzzygd    分析模型
  --fuzziness quick|fine|custom    模糊系数模式（仅 fuzzygd；custom 需 --fz-values）
  --fz-values <list>      自定义模糊系数，如 1,2,3
  --perm N                置换检验次数 0~5000（仅 fuzzygd）
  --title <str>           任务标题
  --upload-id N           复用已上传文件（一次性，消费后不可再用）
  --no-wait               只提交不等待，打印 task_id
  --json                  机器可读输出
```

### 任务与报告

```bash
opgd status <task_id> [--json]              # 查询任务状态
opgd wait <task_id> [--json]                # 等待完成并渲染报告
opgd tasks [--limit N] [--json]             # 历史任务列表
opgd cancel <task_id>                       # 取消排队中/计算中的任务
opgd report <task_id> [--json]              # 终端渲染完整报告
opgd export <task_id> -o <dir> [--unzip] [--png]   # 下载报告 ZIP + 因子/交互 PNG
```

## --json 输出要点

- `trial --json`：顶层 `factor_detector_q_values`（数组，元素含 `Factor`/`q-statistic`）、`applied_config`、`masked_modules`
- `analyze`（wait 后）/`report --json`：顶层 `summary`（含 `top_factor`/`top_q_value`/`significant_factor_count`）、`optimal_params`（按变量分组：`{method, bins, q_value}`）、`factor_detector`、`interaction_detector.pairs|matrix`、`risk_detector`、`ecological_detector`
- `status --json`：`status` 字段 ∈ PENDING/PROCESSING/SUCCESS/FAILED/CANCELLED
- JSON 输出走原生 stdout，无装饰字符，可直接管道解析

## 服务端约束

- 上传 ≤ 50MB，支持 csv/xlsx/xls
- 上传文件一次性：任务终态后服务端删除文件（`--upload-id` 复用会产出 FAILED 任务并退款）
- 任务失败自动返还分析次数（token ledger 记账）
- Y 不得出现在 X 中；`--cat` 列必须属于 X
- 免费通道：服务端自动寻优 + 限流（配合 nginx 约 5 次分析/分钟/IP）
