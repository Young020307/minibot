def run(args: dict) -> dict:
    """
    Standard Skill entry function, called by the Agent
    :param args: Parameter dictionary passed by the Agent, must contain the "text" key
    :return: Result dictionary with status, skill name, count, summary and other information
    """
    # Get the text parameter, set default prompt if missing
    text = args.get("text", "").strip()
    
    # Count character length (excluding extra spaces)
    char_count = len(text)
    
    # Generate adaptive summary based on text length
    if char_count == 0:
        summary = "You have not entered any content"
    elif char_count< 20:
        summary = f"Short content, main expression: {text}"
    else:
        summary = f"Long content, core meaning: {text[:30]}..."
    
    # Return result in standard dictionary format, easy for Agent to parse
    return {
        "status": "success",
        "skill": "counter_summarizer",
        "text_length": char_count,
        "summary": summary,
        "note": "Skill executed successfully, results are ready for Agent to use"
    }