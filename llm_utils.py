# llm_utils.py
def get_llm_content(response):
    """从 llm_call_common 返回值中提取文本内容（兼容新旧格式）"""
    if isinstance(response, dict):
        return response.get("content", "")
    return response