"""Dual writes: a fact stated as a command, then mirrored onto the catalog.

Issue #677. Every module here exists because a read has not moved yet, so
each one is deleted by the issue that moves its reads.
"""
