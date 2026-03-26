# Counter Summarizer Skill Usage Notes
## 1. Parameter Description
- text: Required parameter, type string, the text content to be counted and summarized.
- Note: Extra spaces at the beginning and end of the text will be automatically removed, and the count will be based on the cleaned text.

## 2. Result Explanation
- status: "success" means the skill is executed normally; if there is an error, it will return "failed".
- text_length: The number of characters of the cleaned text (excluding extra spaces).
- summary: Adaptive summary, different formats according to text length.
- note: Auxiliary prompt information, used to prompt the execution status.

## 3. Common Problems
- Problem: The returned text_length is 0.
  Solution: Check if the "text" parameter is passed correctly, or if the input text is all spaces.
- Problem: The summary is truncated.
  Reason: The text length exceeds 20 characters, which is the default adaptive logic of the skill.