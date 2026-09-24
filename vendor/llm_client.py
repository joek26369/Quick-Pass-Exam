"""
LLM Client — 统一的大语言模型客户端

职责:
  ├── 封装 ARK API 调用（支持火山引擎/OpenAI 兼容接口）
  ├── 支持分阶段配置（analyzer/generator/visualizer）
  ├── chat() 返回原始文本，chat_json() 返回解析后的 dict
  └── 错误处理与降级提示

不做的事:
  ✗ 不管理业务逻辑（那是 Analyzer/Generator 的职责）
  ✗ 不做缓存（由调用方自行管理）
  ✗ 不直接读取 web_app.py 的配置（独立加载 data/llm_config.json）

使用示例:
    from llm_client import get_llm_client

    client = get_llm_client("analyzer")
    if client is None:
        # LLM 未启用，降级为 rule-based
        ...
    else:
        result = client.chat_json(system_prompt, user_prompt)
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Optional, Any, Callable

try:
    import requests
except ImportError:
    requests = None


# ============================================================================
# 异常定义
# ============================================================================

class LLMError(Exception):
    """LLM 调用异常基类"""

    def __init__(self, message: str, *, stage: str = "", cause: Optional[Exception] = None):
        super().__init__(message)
        self.stage = stage
        self.cause = cause


class LLMConfigError(LLMError):
    """配置错误（如未配置 API Key）"""


class LLMTimeoutError(LLMError):
    """超时错误"""


class LLMResponseError(LLMError):
    """响应解析错误"""


class LLMDisabledError(LLMError):
    """LLM 未启用"""


@dataclass
class UsageAttempt:
    """脱敏的 provider attempt 计量事件。

    该对象只包含请求元数据和供应商返回的 usage；绝不携带 API key、prompt
    或响应原文。``status`` 是 sent/succeeded/failed，``usage_source`` 在
    provider 没有 usage 时为 unknown，而不是伪造 0。
    """

    call_id: str
    attempt: int
    stage: str
    provider: str
    model: str
    status: str
    request_id: Optional[str] = None
    sent_at: Optional[float] = None
    completed_at: Optional[float] = None
    input_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    usage_source: str = "unknown"
    error_code: Optional[str] = None

    def as_dict(self) -> dict:
        return asdict(self)


# ============================================================================
# 配置加载
# ============================================================================

# 默认配置（仅当配置文件不存在时使用）
_DEFAULT_CONFIG = {
    "provider": "volces",
    "api_key": "",
    "api_url": "",
    "global": {"enabled": True, "last_updated": ""},
    "stages": {
        "analyzer": {"model": "deepseek-v4-flash", "timeout": 180,
                     "temperature": 0.3, "max_tokens": 4096, "enabled": True},
        "generator": {"model": "deepseek-v4-flash", "timeout": 120,
                      "temperature": 0.4, "max_tokens": 4096, "enabled": True},
        "visualizer": {"model": "deepseek-v4-flash", "timeout": 90,
                       "temperature": 0.5, "max_tokens": 4096, "enabled": True},
    },
}


def _find_config_path() -> str:
    raise LLMConfigError("单机包禁止隐式搜索配置；请由入口显式传入 config")


def load_llm_config(config_path: str = "") -> dict:
    """
    加载 LLM 配置（带默认值合并）

    Args:
        config_path: 配置文件路径，留空则自动查找
    """
    path = config_path or _find_config_path()
    cfg = json.loads(json.dumps(_DEFAULT_CONFIG))  # 深拷贝默认值

    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            # 合并顶层
            for k, v in user_cfg.items():
                if k == "stages" and isinstance(v, dict):
                    for sk, sv in v.items():
                        if isinstance(sv, dict):
                            cfg["stages"].setdefault(sk, {})
                            cfg["stages"][sk].update(sv)
                        else:
                            cfg["stages"][sk] = sv
                elif k == "global" and isinstance(v, dict):
                    cfg["global"].update(v)
                else:
                    cfg[k] = v
        except Exception as e:
            print(f"WARNING: 加载 LLM 配置失败 {path}: {e}，使用默认值")
    return cfg


def get_stage_config(stage: str, config: Optional[dict] = None) -> dict:
    """
    获取指定阶段的配置（合并全局和阶段配置）

    Args:
        stage: 阶段名 "analyzer" | "generator" | "visualizer"
        config: 完整配置，留空则自动加载

    Returns:
        合并后的阶段配置，包含: model, timeout, temperature, max_tokens,
        enabled, api_key, api_url, provider, stage_name
    """
    cfg = config or load_llm_config()
    stage_cfg = cfg.get("stages", {}).get(stage, {})

    # 阶段独立配置优先；阶段值为空字符串/None 时回退到全局顶层
    # 用 `or` 而非带默认值的 .get()，确保空字符串也触发回退
    merged = {
        "stage_name": stage,
        "provider": stage_cfg.get("provider") or cfg.get("provider") or "volces",
        "api_url": stage_cfg.get("api_url") or cfg.get("api_url") or "",
        "api_key": stage_cfg.get("api_key") or cfg.get("api_key") or "",
        "model": stage_cfg.get("model") or "deepseek-v4-flash",
        "timeout": stage_cfg.get("timeout") or 180,
        "temperature": stage_cfg.get("temperature") if stage_cfg.get("temperature") is not None else 0.3,
        "max_tokens": stage_cfg.get("max_tokens") or 4096,
        "enabled": stage_cfg.get("enabled", True) and cfg.get("global", {}).get("enabled", True),
    }

    # 全局 key 为空时回退环境变量（webapp 进程 key 走 env，不在 llm_config.json 里）
    return merged


# 可被页面配置的字段（api_key 除外——secret 只写不读）
LLM_STAGE_FIELDS = ("model", "api_url", "timeout", "temperature", "max_tokens", "enabled")


def save_stage_config(stage: str, updates: dict, config_path: str = "") -> dict:
    """把 stage 级覆盖写回 data/llm_config.json（只认 LLM_STAGE_FIELDS，api_key 单独处理）。

    Returns: 写后的 {stage: {field: value}}（api_key 只报 has_key 不回显）。
    """
    path = config_path or _find_config_path()
    cfg = json.loads(json.dumps(_DEFAULT_CONFIG))
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            user = json.load(f)
        for k, v in user.items():
            if k == "stages" and isinstance(v, dict):
                for sk, sv in v.items():
                    cfg["stages"].setdefault(sk, {}).update(sv or {})
            elif k == "global" and isinstance(v, dict):
                cfg["global"].update(v)
            else:
                cfg[k] = v

    st = cfg["stages"].setdefault(stage, {})
    for field in LLM_STAGE_FIELDS:
        if field in updates:
            v = updates[field]
            if field in ("timeout", "max_tokens"):
                v = int(v)
            elif field == "temperature":
                v = float(v)
            elif field == "enabled":
                v = bool(v)
            st[field] = v
    if updates.get("api_key"):  # 空 = 不改
        st["api_key"] = str(updates["api_key"]).strip()

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    reset_client_cache()
    saved = {field: st.get(field) for field in LLM_STAGE_FIELDS if field in st}
    saved["api_key_set"] = bool(st.get("api_key"))
    return {stage: saved}


# ============================================================================
# LLM 客户端
# ============================================================================

class LLMClient:
    """统一的 LLM 客户端"""

    def __init__(self, stage: str = "analyzer", config: Optional[dict] = None,
                 usage_observer: Optional[Callable[[dict], None]] = None):
        """
        Args:
            stage: 阶段名 "analyzer" | "generator" | "visualizer"
            config: 完整配置 dict，留空则自动加载
        """
        self.stage = stage
        self._config = config or load_llm_config()
        self._stage_cfg = get_stage_config(stage, self._config)

        self.api_key: str = self._stage_cfg["api_key"]
        self.api_url: str = self._stage_cfg["api_url"]
        self.model: str = self._stage_cfg["model"]
        self.timeout: int = self._stage_cfg["timeout"]
        self.temperature: float = self._stage_cfg["temperature"]
        self.max_tokens: int = self._stage_cfg["max_tokens"]
        self.enabled: bool = self._stage_cfg["enabled"]
        self.provider: str = self._stage_cfg["provider"]
        # Kept outside the serialised config so callers can safely install a
        # process-local observer.  The config spelling is useful to existing
        # webapp factories and remains backwards compatible.
        self.usage_observer = usage_observer or self._config.get("_usage_observer")
        self.usage_attempts: list[dict] = []
        self.last_usage: Optional[dict] = None
        self.last_usage_error: Optional[str] = None

        if self.api_url and "/chat/completions" not in self.api_url:
            base = self.api_url.rstrip("/")
            self.api_url = f"{base}/chat/completions"

    def set_usage_observer(self, observer: Optional[Callable[[dict], None]]) -> None:
        """Set or clear the per-attempt usage callback."""
        self.usage_observer = observer

    def _emit_usage(self, event: UsageAttempt) -> None:
        record = event.as_dict()
        self.usage_attempts.append(record)
        if event.status == "succeeded":
            self.last_usage = {
                k: record[k] for k in ("input_tokens", "cached_input_tokens", "output_tokens", "usage_source")
            }
        observer = self.usage_observer
        if observer is not None:
            try:
                observer(dict(record))
                self.last_usage_error = None
            except Exception as exc:
                # Accounting must never change the existing chat contract.
                self.last_usage_error = type(exc).__name__

    @staticmethod
    def _usage_from_payload(usage: Any) -> Optional[dict]:
        if not isinstance(usage, dict):
            return None
        def integer(*names):
            for name in names:
                value = usage.get(name)
                if isinstance(value, bool):
                    continue
                if isinstance(value, (int, float)) and value >= 0 and value == value:
                    return int(value)
            return None
        prompt = integer("prompt_tokens", "input_tokens")
        details = usage.get("prompt_tokens_details")
        cached = integer("cached_tokens", "cached_input_tokens")
        if cached is None and isinstance(details, dict):
            cached = integer_from = details.get("cached_tokens")
            if (not isinstance(integer_from, bool) and isinstance(integer_from, (int, float))
                    and integer_from >= 0 and integer_from == integer_from):
                cached = int(integer_from)
            else:
                cached = None
        if cached is None:
            cached = integer("prompt_cache_hit_tokens")
        completion = integer("completion_tokens", "output_tokens")
        if prompt is None and completion is None and cached is None:
            return None
        return {"input_tokens": prompt, "cached_input_tokens": cached,
                "output_tokens": completion, "usage_source": "provider"}

    # ---- 状态检查 ----

    @property
    def is_available(self) -> bool:
        """是否可用（已启用且配置了密钥和端点）"""
        return self.enabled and bool(self.api_key) and bool(self.api_url)

    def check_available(self) -> None:
        """检查是否可用，不可用则抛异常"""
        if not self.enabled:
            raise LLMDisabledError(f"阶段 {self.stage} 的 LLM 未启用", stage=self.stage)
        if not self.api_key:
            raise LLMConfigError(f"API Key 未配置", stage=self.stage)
        if not self.api_url:
            raise LLMConfigError(f"API URL 未配置", stage=self.stage)
        if requests is None:
            raise LLMConfigError("requests 库未安装，请运行 pip install requests", stage=self.stage)

    # ---- 核心调用 ----

    def chat(self, system_prompt: str, user_prompt: str,
             *, temperature: Optional[float] = None,
             max_tokens: Optional[int] = None,
             timeout: Optional[int] = None) -> str:
        """
        调用 LLM 并返回原始文本响应

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            temperature: 覆盖温度参数，留空用阶段配置
            max_tokens: 覆盖最大 token 数
            timeout: 覆盖超时秒数

        Returns:
            LLM 响应的文本内容

        Raises:
            LLMDisabledError: LLM 未启用
            LLMConfigError: 配置不完整
            LLMTimeoutError: 调用超时
            LLMResponseError: 响应解析失败
        """
        self.check_available()
        guard = self._config.get("_credential_guard")
        if guard:
            guard()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }

        actual_timeout = timeout or self.timeout

        # 429 速率限制重试（最多 3 次，退避 5/10/20 秒）
        import time as _time
        try:
            max_retries = max(0, min(3, int(self._config.get("_max_retries", 3))))
        except (TypeError, ValueError):
            max_retries = 3
        backoff_seconds = [5, 10, 20]

        # 流式接收：长生成期间 chunk 持续到达，避免中间层（NAT/防火墙 ~60s 空闲超时）
        # 把整个非流式响应掐成 ChunkedEncodingError。finish_reason 从最后一个 chunk 取。
        payload["stream"] = True

        status = None
        finish_reason = None
        content = None
        call_id = str(uuid.uuid4())
        for attempt in range(max_retries + 1):
            usage = None
            request_id = None
            event = UsageAttempt(call_id=call_id, attempt=attempt + 1,
                                 stage=self.stage, provider=self.provider,
                                 model=self.model, status="sent",
                                 sent_at=None)
            try:
                if guard:
                    guard()
                if guard:
                    # Final dispatch check: the authorization decision and
                    # transport boundary must be adjacent.
                    guard()
                request_scope = None
                before_send = self._config.get("_before_send")
                def transport_post(*post_args, **post_kwargs):
                    # For BYOK this function is invoked by dispatch_request
                    # only after its lease/status transaction and lock hold.
                    # Therefore the callback and sent marker share the true
                    # dispatch boundary, immediately before HTTP transport.
                    if before_send is not None:
                        try:
                            allowed = before_send({
                                "call_id": call_id, "attempt": attempt + 1,
                                "stage": self.stage, "provider": self.provider,
                                "model": self.model, "api_url": self.api_url,
                            })
                            if allowed is False:
                                raise RuntimeError("before_send rejected")
                        except Exception as exc:
                            event.status = "blocked"
                            event.error_code = "BEFORE_SEND_REJECTED"
                            event.completed_at = time.time()
                            self._emit_usage(event)
                            raise LLMResponseError(event.error_code, stage=self.stage, cause=exc) from exc
                    event.status = "sent"
                    event.sent_at = time.time()
                    self._emit_usage(event)
                    return requests.post(*post_args, **post_kwargs)
                if self._config.get("_credential_id"):
                    from byok import dispatch_guard, dispatch_request
                    dispatch_guard(self._config["_credential_user_id"], self._config["_credential_id"])
                    request_scope = lambda *a, **kw: dispatch_request(
                        transport_post, self._config["_credential_user_id"], self._config["_credential_id"], *a, **kw)
                parts: list[str] = []
                finish_reason = None
                # The historical audit marker is kept on the executable
                # transport setup line below.
                request_scope = request_scope or transport_post
                with request_scope(
                    self.api_url, headers=headers, json=payload,
                    timeout=(30, actual_timeout),  # 连接 30s，读超时=总超时（每个 chunk 间重置）
                    stream=True,
                    allow_redirects=False,
                    # Provider endpoints are server-owned; do not inherit a
                    # user-controlled HTTP(S)/SOCKS proxy from the process.
                    proxies={"http": "", "https": ""},
                ) as resp:
                    status = resp.status_code
                    request_id = (getattr(resp, "headers", {}) or {}).get("x-request-id") or \
                        (getattr(resp, "headers", {}) or {}).get("request-id")
                    event.request_id = str(request_id) if request_id else None
                    if status != 200:
                        # Never copy provider response bodies into exceptions:
                        # some providers echo Authorization material.
                        if status == 429 and attempt < max_retries:
                            event.status = "failed"
                            event.error_code = "PROVIDER_HTTP_429"
                            event.completed_at = time.time()
                            self._emit_usage(event)
                            wait = backoff_seconds[attempt]
                            print(f"WARNING: LLM 429 速率限制，{wait}s 后重试 (attempt {attempt+1}/{max_retries})")
                            _time.sleep(wait)
                            continue
                        event.status = "failed"
                        event.error_code = f"PROVIDER_HTTP_{status}"
                        event.completed_at = time.time()
                        self._emit_usage(event)
                        raise LLMResponseError(event.error_code, stage=self.stage)
                    for line in resp.iter_lines(decode_unicode=True):
                        if not line or not line.startswith("data: "):
                            continue
                        data = line[len("data: "):]
                        if data.strip() == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if obj.get("id") and not event.request_id:
                            event.request_id = str(obj["id"])
                        chunk_usage = self._usage_from_payload(obj.get("usage"))
                        if chunk_usage:
                            usage = chunk_usage
                        try:
                            delta = obj["choices"][0]["delta"]
                            if delta.get("content"):
                                parts.append(delta["content"])
                            if obj["choices"][0].get("finish_reason"):
                                finish_reason = obj["choices"][0]["finish_reason"]
                        except (KeyError, IndexError, TypeError):
                            continue
                content = "".join(parts)
                if usage:
                    event.input_tokens = usage["input_tokens"]
                    event.cached_input_tokens = usage["cached_input_tokens"]
                    event.output_tokens = usage["output_tokens"]
                    event.usage_source = usage["usage_source"]
                event.status = "succeeded"
                event.completed_at = time.time()
                self._emit_usage(event)
                break
            except requests.exceptions.Timeout as e:
                event.status = "failed"
                event.error_code = f"PROVIDER_TIMEOUT_{actual_timeout}s"
                event.completed_at = time.time()
                self._emit_usage(event)
                # 超时也走重试+退避（与 429 一致），给上游供应商一次喘息机会，
                # 避免单次慢响应直接判定失败。仅当所有重试用尽后才上抛 LLMTimeoutError。
                if attempt < max_retries:
                    wait = backoff_seconds[attempt]
                    print(f"WARNING: LLM 调用超时（{actual_timeout}s），{wait}s 后重试 (attempt {attempt+1}/{max_retries})")
                    _time.sleep(wait)
                    continue
                raise LLMTimeoutError(
                    f"PROVIDER_TIMEOUT_{actual_timeout}s",
                    stage=self.stage, cause=e,
                ) from e
            except requests.exceptions.RequestException as e:
                event.status = "failed"
                event.error_code = "PROVIDER_UNAVAILABLE"
                event.completed_at = time.time()
                self._emit_usage(event)
                # 连接中途断开（ChunkedEncodingError: Response ended prematurely 等）
                # 与超时同因：长响应被上游掐流，退避重试而非直接失败
                if attempt < max_retries and isinstance(
                    e, (requests.exceptions.ChunkedEncodingError,
                        requests.exceptions.ConnectionError)):
                    wait = backoff_seconds[attempt]
                    print(f"WARNING: LLM 连接中断，{wait}s 后重试 (attempt {attempt+1}/{max_retries})")
                    _time.sleep(wait)
                    continue
                raise LLMResponseError(
                    "PROVIDER_UNAVAILABLE",
                    stage=self.stage, cause=e,
                ) from e
            except LLMError:
                # Includes non-HTTP response errors raised by a provider.
                if event.status == "sent":
                    event.status = "failed"
                    event.error_code = f"PROVIDER_HTTP_{status}" if status else "PROVIDER_ERROR"
                    event.completed_at = time.time()
                    self._emit_usage(event)
                raise

        if content is None:
            raise LLMResponseError("LLM 流式响应为空", stage=self.stage)

        if finish_reason == "length":
            # 截断的 JSON 对调用方必然解析失败——显式抛错让 chat_json 重试梯子翻倍 max_tokens
            raise LLMResponseError(
                f"LLM 响应被 max_tokens={payload['max_tokens']} 截断（finish_reason=length）",
                stage=self.stage,
            )
        return content

    def chat_json(self, system_prompt: str, user_prompt: str,
                  *, temperature: Optional[float] = None,
                  max_tokens: Optional[int] = None,
                  timeout: Optional[int] = None) -> dict:
        """
        调用 LLM 并返回解析后的 JSON dict

        带重试梯子（A/B 实测 deepseek-v4-flash 偶发空响应/坏 JSON）：
        - 空响应 / JSON 解析失败：原参数重试，最多 2 次
        - finish_reason=length 截断：max_tokens 翻倍重试（上限 16384，已实测端点接受）
        - 其余错误（超时/429 重试已尽/HTTP 错误）不在此层重试

        自动处理以下情况：
        - 响应被 ```json ... ``` 代码块包裹
        - 响应前后有多余文本（提取第一个 {...} 块）
        - JSON 解析失败抛 LLMResponseError

        Returns:
            解析后的 dict
        """
        import time as _time

        mt = max_tokens or self.max_tokens
        attempts, backoff = 2, [2]
        last_err: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                content = self.chat(
                    system_prompt, user_prompt,
                    temperature=temperature, max_tokens=mt, timeout=timeout,
                )
            except LLMResponseError as e:
                if "被 max_tokens" not in str(e):
                    raise  # HTTP 错误等不在此层重试；截断错误进入梯子翻倍预算
                last_err = e
                content = None
            if not content or not content.strip():
                if content is not None:
                    last_err = LLMResponseError("LLM 响应为空")
            else:
                try:
                    return self._parse_json_response(content)
                except LLMResponseError as e:
                    last_err = e
            if "被 max_tokens" in str(last_err) and mt < 16384:
                mt = min(mt * 2, 16384)  # 截断 → 翻倍预算重试（chat 内抛的截断错误也走这）
            if attempt < attempts - 1:
                print(f"WARNING: chat_json 第 {attempt + 1}/{attempts} 次失败，"
                      f"{'max_tokens→' + str(mt) + ' ' if '被 max_tokens' in str(last_err) else ''}{backoff[attempt]}s 后重试 ({type(last_err).__name__})")
                _time.sleep(backoff[attempt])
        raise last_err  # type: ignore[misc]

    @staticmethod
    def _parse_json_response(content: str) -> dict:
        """从 LLM 响应中提取 JSON dict"""
        if not content:
            raise LLMResponseError("LLM 响应为空")

        text = content.strip()

        # 1. 去除 markdown 代码块 ```json ... ``` 或 ``` ... ```
        code_block_pattern = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)
        match = code_block_pattern.search(text)
        if match:
            text = match.group(1).strip()

        # 2. 尝试直接解析
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
            if isinstance(result, list):
                return {"_list": result}
        except json.JSONDecodeError:
            pass

        # 3. 提取第一个 {...} 块
        brace_pattern = re.compile(r"\{.*\}", re.DOTALL)
        match = brace_pattern.search(text)
        if match:
            block = match.group(0)
            try:
                result = json.loads(block)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError as e:
                # 尝试修复常见 JSON 错误后重试
                repaired = re.sub(r"//[^\n]*", "", block)           # 去除行注释
                repaired = re.sub(r",\s*([}\]])", r"\1", repaired)  # 去除尾逗号
                try:
                    result = json.loads(repaired)
                    if isinstance(result, dict):
                        return result
                except json.JSONDecodeError:
                    pass
                # 诊断：保存完整内容并打印错误行上下文
                try:
                    dbg_path = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "llm_debug_raw.txt")
                    os.makedirs(os.path.dirname(dbg_path), exist_ok=True)
                    with open(dbg_path, "w", encoding="utf-8") as df:
                        df.write(text)
                except Exception:
                    pass
                lines = text.split("\n")
                ln = e.lineno or 1
                ctx = "\n".join(
                    f"{i+1}: {lines[i]}"
                    for i in range(max(0, ln - 3), min(len(lines), ln + 2))
                )
                raise LLMResponseError(
                    "LLM 响应 JSON 解析失败\n"
                    f"错误位置附近:\n{ctx}\n"
                    f"(完整内容已保存到 data/llm_debug_raw.txt)",
                    cause=e,
                ) from e

        raise LLMResponseError(
            f"LLM 响应中未找到 JSON 对象\n原始内容: {text[:300]}"
        )

    def __repr__(self) -> str:
        return (f"LLMClient(stage={self.stage!r}, model={self.model!r}, "
                f"enabled={self.enabled}, available={self.is_available})")


# ============================================================================
# 模块级单例管理（按阶段缓存）
# ============================================================================

_client_cache: dict[str, LLMClient] = {}


def get_llm_client(stage: str = "analyzer", config: Optional[dict] = None,
                   refresh: bool = False) -> Optional[LLMClient]:
    """
    获取指定阶段的 LLM 客户端（带缓存）

    Args:
        stage: 阶段名 "analyzer" | "generator" | "visualizer"
        config: 完整配置 dict，留空则自动加载
        refresh: 是否强制重新创建（配置变更后使用）

    Returns:
        LLMClient 实例；若 LLM 未启用或配置不完整，返回 None
    """
    if refresh and stage in _client_cache:
        del _client_cache[stage]

    if stage not in _client_cache:
        try:
            client = LLMClient(stage=stage, config=config)
            if client.is_available:
                _client_cache[stage] = client
            else:
                return None
        except Exception as e:
            print(f"WARNING: 创建 LLM 客户端失败 (stage={stage}): {e}")
            return None

    return _client_cache.get(stage)


def reset_client_cache():
    """重置所有缓存的客户端（配置变更后调用）"""
    _client_cache.clear()


# ============================================================================
# 便捷函数
# ============================================================================

def call_llm(stage: str, system_prompt: str, user_prompt: str,
             *, temperature: Optional[float] = None,
             max_tokens: Optional[int] = None,
             timeout: Optional[int] = None) -> Optional[str]:
    """
    便捷调用 LLM（自动获取客户端，失败返回 None）

    使用示例:
        from llm_client import call_llm
        result = call_llm("analyzer", "你是助手", "分析这题")
        if result is None:
            # 降级为 rule-based
            ...
    """
    client = get_llm_client(stage)
    if client is None:
        return None
    try:
        return client.chat(system_prompt, user_prompt,
                           temperature=temperature, max_tokens=max_tokens,
                           timeout=timeout)
    except LLMError as e:
        print(f"WARNING: LLM 调用失败 (stage={stage}): {e}")
        return None


def call_llm_json(stage: str, system_prompt: str, user_prompt: str,
                  *, temperature: Optional[float] = None,
                  max_tokens: Optional[int] = None,
                  timeout: Optional[int] = None) -> Optional[dict]:
    """
    便捷调用 LLM 并返回 JSON（自动获取客户端，失败返回 None）
    """
    client = get_llm_client(stage)
    if client is None:
        return None
    try:
        return client.chat_json(system_prompt, user_prompt,
                                temperature=temperature, max_tokens=max_tokens,
                                timeout=timeout)
    except LLMError as e:
        print(f"WARNING: LLM JSON 调用失败 (stage={stage}): {e}")
        return None
