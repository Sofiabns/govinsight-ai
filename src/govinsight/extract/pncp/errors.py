class PNCPError(RuntimeError):
    """Base error for failures at the PNCP boundary."""


class PNCPHTTPError(PNCPError):
    def __init__(self, *, status_code: int, endpoint: str, attempt: int) -> None:
        self.status_code = status_code
        self.endpoint = endpoint
        self.attempt = attempt
        super().__init__(
            f"PNCP request failed with HTTP {status_code} at {endpoint} on attempt {attempt}"
        )


class PNCPResponseError(PNCPError):
    def __init__(self, *, endpoint: str, reason: str) -> None:
        self.endpoint = endpoint
        self.reason = reason
        super().__init__(f"PNCP returned an invalid response at {endpoint}: {reason}")


class PNCPRetryExhausted(PNCPError):
    def __init__(self, *, endpoint: str, attempts: int) -> None:
        self.endpoint = endpoint
        self.attempts = attempts
        super().__init__(f"PNCP request exhausted {attempts} attempts at {endpoint}")
