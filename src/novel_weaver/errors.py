class NovelError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = 3, retryable: bool = False, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.retryable = retryable
        self.details = details or {}


def validation_error(exc):
    """Do not echo manuscript text, secret inputs, or Pydantic context objects."""
    issues = [{"path": ".".join(map(str, item["loc"])), "type": item["type"], "message": item["msg"]}
              for item in exc.errors(include_input=False, include_url=False, include_context=False)]
    return NovelError("INVALID_INPUT", "Request does not match the tool schema", 2, details={"issues": issues})


def error_envelope(error):
    return {"schema_version": 1, "status": "error", "book_id": None, "revision": None,
            "data": {}, "warnings": [], "next_actions": [],
            "error": {"code": error.code, "message": error.message, "retryable": error.retryable,
                      "exit_code": error.exit_code, "details": error.details}}


def require(condition, code: str, message: str, exit_code: int = 3):
    if not condition:
        raise NovelError(code, message, exit_code)
