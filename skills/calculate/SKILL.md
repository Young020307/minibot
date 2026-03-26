---
name: calculate
description: 统计用户输入的文本字数
---

## 功能说明

统计用户输入的文本字数。

## 调用方式

使用 `bash_exec` 工具，通过 Python 内联脚本执行，**无需任何外部文件**：

```python
bash_exec("""python -c "
import sys, json
sys.path.insert(0, 'c:/Users/Younson/Desktop/Agent/minibot')
from skills.calculate.script.main import run
result = run({'text': '''在此处替换为要统计的文本'''})
print(json.dumps(result, ensure_ascii=False, indent=2))
" """)
```

### 参数说明

| 参数 | 类型   | 必填 | 说明             |
|------|--------|------|------------------|
| text | string | ✅   | 需要统计的文本内容 |

### 返回格式示例

```json
{
  "status": "success",
  "skill": "counter_summarizer",
  "text_length": 20,
  "note": "Skill executed successfully"
}
```

## 使用时机

当用户请求以下内容时调用此技能：
- 统计文字/字数/字符数
- 分析文本长度
