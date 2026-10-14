class ComfyError(Exception):
    def __init__(self, message, code="COMFY_INVALID_REQUEST", status=400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status
