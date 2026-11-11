class NovelError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = 3, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.retryable = retryable


def require(condition, code: str, message: str, exit_code: int = 3):
    if not condition:
        raise NovelError(code, message, exit_code)
