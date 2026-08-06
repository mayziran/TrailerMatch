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
        self._http = None  # 当前底层 httpx 客户端，关闭它可中止进行中的请求
        self._aborted = False

    def abort(self) -> None:
        """中止当前进行中的请求：关闭底层连接，阻塞的请求会立刻抛错。"""
        self._aborted = True
        http, self._http = self._http, None
        if http is not None:
            try:
                http.close()
            except Exception:
                pass

    def _client(self):
        if self._aborted:
            raise RuntimeError("匹配已取消")
        import httpx
        from openai import OpenAI
        http = httpx.Client(timeout=120)
        self._http = http
        return OpenAI(
            base_url=self.config.api_base_url or None,
            api_key=self.config.api_key or "EMPTY",
            timeout=120,
            max_retries=1,
            http_client=http,
        )

    def _complete(self, prompt: str) -> str:
        """发起一次对话补全，自动兼容不支持 response_format 的接口。"""
        if self._aborted:
            raise RuntimeError("匹配已取消")
        client = self._client()
        messages = [
            {"role": "system", "content": "你是一个严谨的电影匹配助手，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ]
        try:
            try:
                response = client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    temperature=self.config.temperature,
                    response_format={"type": "json_object"},
                )
            except Exception:
                response = client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    temperature=self.config.temperature,
                )
            return response.choices[0].message.content
        finally:
            # 请求结束，关闭底层连接；若请求中途被 abort()，此处已无连接可关
            http, self._http = self._http, None
            if http is not None:
                try:
                    http.close()
                except Exception:
                    pass

    def ask_match(self, trailer_name: str, candidate_movies: list) -> dict:
        """让 AI 从候选正片名中为单个预告片选择最佳匹配。

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

        content = self._complete(prompt)
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

    def ask_batch(self, trailer_names: list, movie_names: list) -> list:
        """一次调用为所有预告片匹配正片。

        返回与 trailer_names 对齐的列表，每项结构同 ask_match。
        """
        trailer_text = "\n".join(
            f"{i}. {name}" for i, name in enumerate(trailer_names)
        )
        movie_text = "\n".join(
            f"{i}. {name}" for i, name in enumerate(movie_names)
        )

        prompt = f"""你是电影资料匹配助手。
下面有 {len(trailer_names)} 个预告片文件名和 {len(movie_names)} 个正片文件夹名。
请为每个预告片从正片列表中找到最佳匹配。

要求:
- 忽略文件名中的年份、清晰度、编码、网站水印、trailer/teaser/sample 等噪声词后再比较。
- 如果某个预告片与任何正片都不匹配，movie 输出 null。
- matches 必须包含所有预告片编号，一个都不能少。
- 只输出一个 JSON 对象，不要输出其它内容。

预告片列表:
{trailer_text}

正片列表:
{movie_text}

输出格式(严格 JSON):
{{"matches": [{{"index": 预告片编号, "movie": "正片完整名称或null", "confidence": 0到100的整数, "reason": "简短理由"}}, ...]}}"""

        content = self._complete(prompt)
        data = _extract_json(content)
        matches = data.get("matches")
        if not isinstance(matches, list):
            raise ValueError(f"批量匹配返回格式错误: {content[:200]}")

        result_map = {}
        for item in matches:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            result_map[idx] = item

        results = []
        for i in range(len(trailer_names)):
            item = result_map.get(i)
            if item is None:
                results.append({
                    "movie": None,
                    "confidence": 0,
                    "reason": "AI 未返回该条匹配结果",
                })
                continue
            movie = item.get("movie")
            if movie in (None, "", "null"):
                movie = None
            confidence = item.get("confidence", 0)
            if isinstance(confidence, (int, float)):
                confidence = max(0, min(100, int(confidence)))
            else:
                confidence = 0
            results.append({
                "movie": movie,
                "confidence": confidence,
                "reason": str(item.get("reason", "")),
            })
        return results
