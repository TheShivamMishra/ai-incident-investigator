"""Meter every provider attempt, including calls in investigations that fail."""
import copy


class BudgetExceeded(RuntimeError):
    pass


class MeteredProvider:
    def __init__(self, request_fn, max_calls=100, max_tokens=100000):
        if type(max_calls) is not int or max_calls < 1 or type(max_tokens) is not int or max_tokens < 1:
            raise ValueError("API budgets must be positive integers")
        self.request_fn = request_fn
        self.max_calls, self.max_tokens = max_calls, max_tokens
        self.calls = 0
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self.attempts = []

    def __call__(self, payload):
        if self.calls >= self.max_calls or sum(self.usage.values()) >= self.max_tokens:
            raise BudgetExceeded("Batch API budget exhausted; no further requests sent")
        self.calls += 1
        attempt = {"request": copy.deepcopy(payload), "response": None, "error": None}
        self.attempts.append(attempt)
        try:
            response = self.request_fn(payload)
            attempt["response"] = copy.deepcopy(response)
            usage = response.get("usage", {})
            if any(type(usage.get(k)) is not int or usage[k] < 0 for k in self.usage):
                # Unknown usage cannot be treated as zero when controlling a batch.
                self.max_calls = self.calls
                raise RuntimeError("Provider omitted valid usage; batch halted to avoid unmetered requests")
            for key in self.usage:
                self.usage[key] += usage[key]
            return response
        except Exception as error:
            attempt["error"] = type(error).__name__
            raise

    def snapshot(self):
        return {"api_calls": self.calls, "usage": dict(self.usage)}
