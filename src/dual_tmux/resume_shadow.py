"""Compatibility aliases. ResumeAttempt is the authoritative worker."""

from .resume_attempt import AtomicResumeStateStore as AtomicShadowStateStore
from .resume_attempt import ResumeAttempt as ResumeShadow

__all__ = ["AtomicShadowStateStore", "ResumeShadow"]
