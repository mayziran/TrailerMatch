"""OpenAI 兼容接口封装。

通过 openai SDK 的自定义 base_url / api_key 兼容所有
OpenAI 风格的服务（OpenAI、Azure、DeepSeek、通义、本地 Ollama 等）。
"""
import json
import re

from .config import Config


def _extract_json(text: str):
    """从模型输出中稳健地提取 JSON 对象。"""
    text = text.strip()
    # 去掉可能的 markdown 代码块围栏
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试截取第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"无法从模型输出解析 JSON: {text[:200]}")


class AIClient:
    def __init__(self, config: Config):
        self.config = config

    def _client(self):
        from openai import OpenAI
        return OpenAI(
            base_url=self.config.api_base_url or None,
            api_key=self.config.api_key or "EMPTY",
            timeout=120,
            max_retries=1,
        )

    def ask_match(self, trailer_name: str, candidate_movies: list) -> dict:
        """让 AI 从候选正片名中为预告片选择最佳匹配。

        返回结构: {"movie": str|None, "confidence": int, "reason": str}
        """
        numbered = [f"{i}. {name}" for i, name in enumerate(candidate_movies)]
        candidate_text = "\n".join(numbered) if numbered else "(无候选)"

        prompt = f"""你是电影资料匹配助手。有一个预告片文件名为:
「{trailer_name}」

请从下面的候选正片列表中选择与它匹配度最高的一部电影。
要求:
- 忽略文件名中的年份、清晰度、编码、网站水印、trailer/teaser/sample 等噪声词后再比较。
- 如果存在明显匹配的候选，输出它的编号所对应的完整名称。
- 如果所有候选都不匹配，则 movie 输出 null。
- 只输出一个 JSON 对象，不要输出其它内容。

候选正片:
{candidate_text}

输出格式(严格 JSON):
{{"movie": "候选完整名称或 null", "confidence": 0到100的整数, "reason": "简短理由"}}"""

        try:
            client = self._client()
            response = client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": "你是一个严谨的电影匹配助手，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.config.temperature,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
        except Exception:
            # 部分兼容接口不支持 response_format，去掉后重试
            client = self._client()
            response = client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": "你是一个严谨的电影匹配助手，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.config.temperature,
            )
            content = response.choices[0].message.content

        data = _extract_json(content)
        movie = data.get("movie")
        if movie in (None, "", "null"):
            movie = None
        confidence = data.get("confidence", 0)
        if isinstance(confidence, (int, float)):
            confidence = max(0, min(100, int(confidence)))
        else:
            confidence = 0
        return {
            "movie": movie,
            "confidence": confidence,
            "reason": str(data.get("reason", "")),
        }
