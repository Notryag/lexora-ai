class CaseNotFoundError(LookupError):
    pass


class MaterialNotFoundError(LookupError):
    pass


class MaterialParseError(ValueError):
    pass


class MaterialLimitError(ValueError):
    pass


class EmbeddingUnavailableError(RuntimeError):
    pass


class LegalSourceNotFoundError(LookupError):
    pass


class DuplicateLegalSourceError(ValueError):
    pass


class CaseLawSourceNotFoundError(LookupError):
    pass


class DuplicateCaseLawSourceError(ValueError):
    pass


class CaseRunNotFoundError(LookupError):
    pass


class ActiveCaseRunNotFoundError(LookupError):
    pass


class RunCancelledError(RuntimeError):
    pass
