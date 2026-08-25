from dataclasses import dataclass

import requests

USER_AGENT = "uptime-monitor/1.0 (+https://github.com/chanllawala/uptime-monitor)"


@dataclass(frozen=True)
class CheckResult:
    is_up: bool
    status_code: int | None
    response_time_ms: float | None
    error: str | None

    @property
    def summary(self) -> str:
        if self.is_up:
            return f"HTTP {self.status_code} in {self.response_time_ms:.0f}ms"
        if self.status_code is not None:
            return f"HTTP {self.status_code} (expected different status)"
        return self.error or "unknown error"


def perform_check(
    url: str,
    method: str = "GET",
    expected_status: int = 200,
    timeout_seconds: int = 10,
    session: requests.Session | None = None,
) -> CheckResult:
    """Poll a URL once and classify the outcome.

    Network faults and unexpected status codes are both "down", but they are
    recorded differently so the dashboard can distinguish "the host is
    unreachable" from "the host answered with a 500".
    """
    requester = session or requests
    try:
        response = requester.request(
            method.upper(),
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
    except requests.Timeout:
        return CheckResult(False, None, None, f"timed out after {timeout_seconds}s")
    except requests.ConnectionError as exc:
        return CheckResult(False, None, None, f"connection error: {_brief(exc)}")
    except requests.RequestException as exc:
        return CheckResult(False, None, None, f"request failed: {_brief(exc)}")

    elapsed_ms = response.elapsed.total_seconds() * 1000
    is_up = response.status_code == expected_status
    error = None if is_up else f"expected {expected_status}, got {response.status_code}"
    return CheckResult(is_up, response.status_code, elapsed_ms, error)


def _brief(exc: Exception, limit: int = 200) -> str:
    text = str(exc)
    return text if len(text) <= limit else text[: limit - 1] + "…"
