# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.1] - 2026-11-17

### 修复

- Windows 非 UTF-8 控制台/管道的 UnicodeEncodeError（stdout/stderr 强制 UTF-8）

### 变更

- 项目更名：「基于最优参数的地理探测器（OPGD）」，补充算法出处（Song et al., 2020）
- 仓库迁移至 github.com/seedgcoding/OPGD_CLI

## [0.1.0] - 2026-11-12

### 新增

- 双通道支持：免登录试用（`opgd trial`）与正式账号通道（`opgd login` + `opgd analyze`）
- 完整命令集：`login` / `logout` / `whoami` / `upload` / `analyze` / `status` / `wait` / `tasks` / `cancel` / `report` / `export`
- 支持 `opgd` 与 `fuzzygd`（模糊地理探测器）两种分析模型
- 终端 Rich 渲染：因子/交互/风险/生态四探测器报告
- 报告导出：ZIP 下载（可选解压）+ 因子/交互探测器 PNG 图表
- `--json` 机器可读输出（适合脚本与管道）
- 任务轮询：指数退避 + Ctrl+C 中断不丢任务
- 系统代理自动降级直连（并记住结论）
- `--password-stdin` 脚本化登录
- 完整异常处理：401 过期提示、429 限流提示、额度不足、任务失败原因透传
- 37 个单元测试（respx 模拟，不依赖线上）

### 已知限制

- 平台上传文件为一次性（任务结束后服务端删除），`--upload-id` 只能复用未消费的上传
- 分类变量必须通过 `--cat` 显式声明
