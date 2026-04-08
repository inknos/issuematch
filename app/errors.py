"""Hierarchical application error classes mapped to HTTP status codes.

Every leaf error carries a machine-readable ``error_code`` and a human-readable
``detail`` default.  Raise them exactly like ``HTTPException``::

    raise IssueNotFoundError              # uses defaults
    raise EmptyFieldError("Display name required")  # custom message

A global exception handler in ``main.py`` serialises any ``AppError`` into a
uniform JSON envelope::

    {"error": {"code": "ISSUE_NOT_FOUND", "message": "Issue not found", "status": 404}}
"""

from __future__ import annotations

from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class AppError(HTTPException):
    """Root of the application error hierarchy."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"
    default_detail: str = "An unexpected error occurred"

    def __init__(self, detail: str | None = None) -> None:  # noqa: D107
        super().__init__(
            status_code=self.status_code,
            detail=detail or self.default_detail,
        )


# =========================================================================
# 400 — Bad Request
# =========================================================================


class BadRequestError(AppError):
    """The request is invalid or cannot be processed."""

    status_code = 400
    error_code = "BAD_REQUEST"
    default_detail = "Bad request"


class EmptyFieldError(BadRequestError):
    """A required field was empty or blank."""

    error_code = "EMPTY_FIELD"
    default_detail = "Required field must not be empty"


class PasswordTooShortError(BadRequestError):
    """The supplied password does not meet the minimum length."""

    error_code = "PASSWORD_TOO_SHORT"
    default_detail = "Password must be at least 8 characters"


class NoPasswordSetError(BadRequestError):
    """The user account has no password; an admin must set one first."""

    error_code = "NO_PASSWORD_SET"
    default_detail = "No password set — ask an admin to set one"


class BatchTooLargeError(BadRequestError):
    """The batch payload exceeds the maximum allowed size."""

    error_code = "BATCH_TOO_LARGE"
    default_detail = "Batch size must not exceed 100 items"


class MissingConfigError(BadRequestError):
    """A required server-side configuration value is absent."""

    error_code = "MISSING_CONFIG"
    default_detail = "No GitHub token configured"


# =========================================================================
# 401 — Authentication
# =========================================================================


class AuthenticationError(AppError):
    """The request lacks valid authentication credentials."""

    status_code = 401
    error_code = "AUTHENTICATION_ERROR"
    default_detail = "Authentication failed"


class InvalidCredentialsError(AuthenticationError):
    """The username or password is incorrect."""

    error_code = "INVALID_CREDENTIALS"
    default_detail = "Invalid username or password"


class NotAuthenticatedError(AuthenticationError):
    """No session or bearer token was provided."""

    error_code = "NOT_AUTHENTICATED"
    default_detail = "Not authenticated"


class WrongPasswordError(AuthenticationError):
    """The current password supplied for a change-password flow is wrong."""

    error_code = "WRONG_PASSWORD"
    default_detail = "Current password is incorrect"


# =========================================================================
# 403 — Authorization
# =========================================================================


class AuthorizationError(AppError):
    """The authenticated user is not allowed to perform this action."""

    status_code = 403
    error_code = "AUTHORIZATION_ERROR"
    default_detail = "Forbidden"


class InsufficientPermissionsError(AuthorizationError):
    """The user's role is too low for the requested operation."""

    error_code = "INSUFFICIENT_PERMISSIONS"
    default_detail = "Insufficient permissions"


class ForbiddenAccessError(AuthorizationError):
    """Access to another user's resources is not permitted."""

    error_code = "FORBIDDEN_ACCESS"
    default_detail = "Cannot access other users' data"


class SelfActionError(AuthorizationError):
    """The action cannot be performed on the caller's own account."""

    error_code = "SELF_ACTION_FORBIDDEN"
    default_detail = "Cannot perform this action on yourself"


class RoleEscalationError(AuthorizationError):
    """The requested role exceeds the caller's own privilege level."""

    error_code = "ROLE_ESCALATION"
    default_detail = "Cannot escalate beyond your own role"


# =========================================================================
# 404 — Not Found
# =========================================================================


class NotFoundError(AppError):
    """The requested resource does not exist."""

    status_code = 404
    error_code = "NOT_FOUND"
    default_detail = "Resource not found"


class IssueNotFoundError(NotFoundError):
    """No issue matches the given identifier."""

    error_code = "ISSUE_NOT_FOUND"
    default_detail = "Issue not found"


class VoteNotFoundError(NotFoundError):
    """No vote matches the given identifier."""

    error_code = "VOTE_NOT_FOUND"
    default_detail = "Vote not found"


class UserNotFoundError(NotFoundError):
    """No user matches the given identifier."""

    error_code = "USER_NOT_FOUND"
    default_detail = "User not found"


class TokenNotFoundError(NotFoundError):
    """No API token matches the given identifier."""

    error_code = "TOKEN_NOT_FOUND"
    default_detail = "Token not found"


# =========================================================================
# 409 — Conflict
# =========================================================================


class ConflictError(AppError):
    """The request conflicts with the current state of a resource."""

    status_code = 409
    error_code = "CONFLICT"
    default_detail = "Resource conflict"


class DuplicateVoteError(ConflictError):
    """A vote for this issue already exists for the user."""

    error_code = "DUPLICATE_VOTE"
    default_detail = "Vote already exists"


class DuplicateUsernameError(ConflictError):
    """A user with this username already exists."""

    error_code = "DUPLICATE_USERNAME"
    default_detail = "Username already exists"


# =========================================================================
# 502 — External Service
# =========================================================================


class ExternalServiceError(AppError):
    """A request to an upstream service failed."""

    status_code = 502
    error_code = "EXTERNAL_SERVICE_ERROR"
    default_detail = "External service request failed"


class GitHubAPIError(ExternalServiceError):
    """The GitHub API returned an error response."""

    error_code = "GITHUB_API_ERROR"
    default_detail = "GitHub API request failed"
