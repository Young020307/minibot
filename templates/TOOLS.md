# Tool Usage Notes

# Cron工具
使用 cron 工具来安排提醒或周期性任务。

参数：
- action：取值为 "add"（添加）、"list"（列出）或 "remove"（删除）
- message：提醒内容或任务描述
- is_task：布尔值。设为 false：用于纯提醒（仅输出消息，无需 Agent 执行任何操作），设为 true：用于任务（需要 Agent 调用工具、推理或搜索来完成）

适用场景：
- 需要精确时间执行（如“每天早上 9 点”，“每 15 分钟”）
- 一次性提醒（如“20 分钟后提醒我”）

示例
- 固定间隔提醒（必须设置 is_task=false）：
cron(action="add", message="该休息一下啦！", every_seconds=1200, is_task=false)
- 动态间提醒（必须设置 is_task=true）：
cron(action="add", message="帮我总结新闻！", every_seconds=1200, is_task=true)

# Heartbeat任务
当用户需要设置循环 / 周期性任务时，更新 `HEARTBEAT.md`，而非是使用 cron 工具来提醒。
你会按照配置的心跳间隔检查 `HEARTBEAT.md` 文件，绝对路径为：“C:\Users\Younson\Desktop\Agent\minibot\templates\HEARTBEAT.md。

请使用文件工具管理周期性任务：
- 添加：先用 `read_file` 读取全文，将新任务插入 `<!-- Add your periodic tasks below this line -->` 注释之后，再用 `write_file` 整体写回
- 移除：先用 `read_file` 读取全文，将目标条目从 `## Active Tasks` 移动到 `## Completed` 区块，再用 `write_file` 整体写回
- 禁止直接使用 `edit_file` 追加到 HEARTBEAT.md，以免破坏文件结构

# 注意cron工具和Heartbeat任务的关注点不同
如果用户明确要求“每 15 分钟发送新闻”，应使用 Cron 工具，而非修改 HEARTBEAT.md。