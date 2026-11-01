"""Conservative token accounting: missing upstream usage stays distinguishable."""

import json


def usage_counts(payload):
    try:
        value = json.loads(payload) if isinstance(payload, str) else payload
        if not isinstance(value, dict):
            return None
        value = value.get("usage") or value.get("response", {}).get("usage") or value.get("message", {}).get("usage")
        if not isinstance(value, dict) or not value:
            return None
        result = {}
        for field, alternate in (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens"), ("total_tokens", "total_tokens")):
            raw = value.get(field, value.get(alternate))
            result[field] = max(0, int(raw)) if raw is not None and not isinstance(raw, bool) else None
        if result["total_tokens"] is None and result["input_tokens"] is not None and result["output_tokens"] is not None:
            result["total_tokens"] = result["input_tokens"] + result["output_tokens"]
        if result["total_tokens"] is not None and result["total_tokens"] > (result["input_tokens"] or 0) + (result["output_tokens"] or 0):
            result["input_tokens"] = result["output_tokens"] = None
        return result if any(value is not None for value in result.values()) else None
    except (ValueError, TypeError, AttributeError):
        return None


def estimate_usage(body, response):
    prompt = max(1, len(json.dumps(body, ensure_ascii=False)) // 4)
    completion = max(0, (len(response) if isinstance(response, str) else int(response)) // 4)
    return {"input_tokens": prompt, "output_tokens": completion, "total_tokens": prompt + completion}
