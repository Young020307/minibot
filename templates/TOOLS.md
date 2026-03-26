# Tool Usage Notes

工具签名会通过函数调用自动提供。
本文件用于记录非显而易见的约束条件与使用模式。

## exec — 安全限制

- 命令可配置超时时间（默认 60 秒）
- 危险命令已被屏蔽（rm -rf、format、dd、shutdown 等）
- 输出内容超过 10000 字符时会被截断
- `restrictToWorkspace` 配置项可将文件访问权限限制在工作区内。

## cron — 定时提醒

- 请参考定时任务（`cron`）技能了解使用方法。
