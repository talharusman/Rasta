# OWNER: Member 3
# Shared HTTP helper for the provider adapters.
#  - per-service timeout (NADRA 4s, Raast 6s, SMS 4s), enforced with asyncio.wait_for
#    so it also holds for in-process transports that ignore httpx timeouts
#  - retries ONLY for safe reads (max 3 attempts, backoff 0.5s/1s/2s), only on
#    timeout / 5xx / connection errors, never on 4xx
#  - simple circuit breaker per service (3 consecutive failures -> open 30s)
#  - one structured log line per attempt (never logs keys, bodies or phone numbers)
# request() never raises: every problem becomes an HttpOutcome.
import asyncio
import json as jsonlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import httpx

logger = logging.getLogger("m3.providers.http")

SERVICE_TIMEOUTS = {"nadra": 4.0, "raast": 6.0, "sms": 4.0}
MAX_ATTEMPTS = 3
RETRY_BACKOFF = (0.5, 1.0, 2.0)
BREAKER_THRESHOLD = 3
BREAKER_OPEN_SECONDS = 30.0

# Outcome kinds
RESPONSE = "response"  # an HTTP response with status < 500 (2xx, 3xx, 4xx)
SERVER_ERROR = "server_error"  # 5xx still failing after allowed attempts
TIMEOUT = "timeout"
CONNECTION_ERROR = "connection_error"
CIRCUIT_OPEN = "circuit_open"  # nothing was sent
FAILURE_KINDS = (SERVER_ERROR, TIMEOUT, CONNECTION_ERROR)


class CircuitBreaker:
    def __init__(
        self,
        threshold: int = BREAKER_THRESHOLD,
        open_seconds: float = BREAKER_OPEN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.threshold = threshold
        self.open_seconds = open_seconds
        self.clock = clock
        self.failures = 0
        self.opened_at: Optional[float] = None

    def allow(self) -> bool:
        """Closed -> True. Open -> False until the cool-down passes, then one
        trial is allowed (half-open): a failure re-opens it, a success closes it."""
        if self.failures < self.threshold:
            return True
        return self.clock() - (self.opened_at or 0.0) >= self.open_seconds

    @property
    def is_open(self) -> bool:
        return not self.allow()

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = self.clock()


@dataclass
class HttpOutcome:
    kind: str
    status_code: Optional[int] = None
    body: bytes = b""
    attempts: int = 0
    duration_ms: int = 0
    error: Optional[str] = None

    @property
    def is_response(self) -> bool:
        return self.kind == RESPONSE

    @property
    def is_success(self) -> bool:
        return self.kind == RESPONSE and self.status_code is not None and 200 <= self.status_code < 300

    @property
    def request_may_have_reached_provider(self) -> bool:
        """True when a non-idempotent call may have been processed anyway."""
        return self.kind in FAILURE_KINDS

    def json(self) -> Any:
        """Parse the body. Raises ValueError on invalid JSON."""
        return jsonlib.loads(self.body)


class ServiceClient:
    def __init__(
        self,
        service: str,
        base_url: str,
        api_key: str,
        timeout: Optional[float] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        breaker: Optional[CircuitBreaker] = None,
    ):
        self.service = service
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout if timeout is not None else SERVICE_TIMEOUTS[service]
        self.breaker = breaker or CircuitBreaker()
        self._transport = transport
        self._client: Optional[httpx.AsyncClient] = None
        self._client_loop: Optional[asyncio.AbstractEventLoop] = None

    def _get_client(self) -> httpx.AsyncClient:
        # An AsyncClient is tied to the event loop that first used it. Background agent
        # runs may use a different loop, so rebuild the client when the loop changes.
        loop = asyncio.get_running_loop()
        if self._client is None or self._client_loop is not loop:
            self._client = httpx.AsyncClient(base_url=self.base_url, transport=self._transport)
            self._client_loop = loop
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _log(self, endpoint: str, attempt: int, status_code: Optional[int], duration_ms: int,
             outcome: str, case_id: Optional[str], error: Optional[str] = None) -> None:
        line = {
            "service": self.service,
            "endpoint": endpoint,
            "attempt": attempt,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "outcome": outcome,
            "case_id": case_id,
        }
        if error:
            line["error"] = error
        level = logging.INFO if outcome == RESPONSE else logging.WARNING
        logger.log(level, "provider_call %s", jsonlib.dumps(line))

    async def _attempt(self, method: str, path: str, json_body: Any, params: Any,
                       headers: Dict[str, str]) -> HttpOutcome:
        try:
            response = await asyncio.wait_for(
                self._get_client().request(
                    method, path, json=json_body, params=params, headers=headers, timeout=self.timeout
                ),
                timeout=self.timeout,
            )
        except (TimeoutError, httpx.TimeoutException):
            return HttpOutcome(TIMEOUT, error=f"{self.service} timed out after {self.timeout}s")
        except httpx.TransportError as exc:
            return HttpOutcome(CONNECTION_ERROR, error=f"{self.service} connection error: {type(exc).__name__}")
        except Exception as exc:  # never raise to callers
            return HttpOutcome(CONNECTION_ERROR, error=f"{self.service} unexpected error: {type(exc).__name__}")
        if response.status_code >= 500:
            return HttpOutcome(
                SERVER_ERROR, response.status_code, response.content,
                error=f"{self.service} returned HTTP {response.status_code}",
            )
        return HttpOutcome(RESPONSE, response.status_code, response.content)

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        safe: bool = False,
        case_id: Optional[str] = None,
    ) -> HttpOutcome:
        """safe=True marks a read with no side effects: it may be retried.
        safe=False is attempted exactly once."""
        send_headers = {"X-Mock-Api-Key": self.api_key, **(headers or {})}
        max_attempts = MAX_ATTEMPTS if safe else 1
        endpoint = f"{method} {path}"
        started = time.perf_counter()
        last: Optional[HttpOutcome] = None

        for attempt in range(1, max_attempts + 1):
            if not self.breaker.allow():
                if last is not None:  # the breaker opened during this call: keep the real error
                    break
                last = HttpOutcome(CIRCUIT_OPEN, attempts=0, error=f"circuit open for {self.service}")
                self._log(endpoint, attempt, None, 0, CIRCUIT_OPEN, case_id, last.error)
                return last

            attempt_start = time.perf_counter()
            outcome = await self._attempt(method, path, json_body, params, send_headers)
            attempt_ms = int((time.perf_counter() - attempt_start) * 1000)
            outcome.attempts = attempt
            last = outcome

            if outcome.kind in FAILURE_KINDS:
                self.breaker.record_failure()
            else:
                self.breaker.record_success()  # 2xx/4xx: the service itself is up
            self._log(endpoint, attempt, outcome.status_code, attempt_ms, outcome.kind, case_id, outcome.error)

            if outcome.kind not in FAILURE_KINDS:
                break
            if attempt < max_attempts:
                await asyncio.sleep(RETRY_BACKOFF[attempt - 1])

        assert last is not None
        last.duration_ms = int((time.perf_counter() - started) * 1000)
        return last
