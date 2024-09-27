# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Span's Span class and related functionality."""

import types
from typing import Any, Dict, Optional, Union

from opentelemetry import trace as otel_trace_api
from opentelemetry.sdk import trace as otel_trace_sdk
from opentelemetry.util import types as otel_types


class Span(otel_trace_api.Span):
    """Chromium specific otel span implementation."""

    def __init__(self, inner: otel_trace_sdk.Span) -> None:
        self._inner = inner

    def end(self, end_time: Optional[int] = None) -> None:
        self._inner.end(end_time=end_time)

    def get_span_context(self) -> otel_trace_api.SpanContext:
        return self._inner.get_span_context()

    def set_attributes(
            self, attributes: Dict[str, otel_types.AttributeValue]) -> None:
        self._inner.set_attributes(attributes)

    def set_attribute(self, key: str, value: otel_types.AttributeValue) -> None:
        self._inner.set_attribute(key, value)

    def add_event(
        self,
        name: str,
        attributes: otel_types.Attributes = None,
        timestamp: Optional[int] = None,
    ) -> None:
        self._inner.add_event(name, attributes=attributes, timestamp=timestamp)

    def update_name(self, name: str) -> None:
        self._inner.update_name(name)

    def is_recording(self) -> bool:
        return self._inner.is_recording()

    def set_status(
        self,
        status: Union[otel_trace_api.Status, otel_trace_api.StatusCode],
        description: Optional[str] = None,
    ) -> None:
        self._inner.set_status(status, description)

    def record_exception(
        self,
        exception: Exception,
        attributes: otel_types.Attributes = None,
        timestamp: Optional[int] = None,
        escaped: bool = False,
    ) -> None:
        # Create a mutable dict from the passed attributes or create a new dict
        # if empty or null. This ensures that the passed dict is not mutated.
        attributes = dict(attributes or {})
        if hasattr(exception, "failed_packages") and isinstance(
                exception.failed_packages, list):
            attributes["failed_packages"] = [
                str(f) for f in exception.failed_packages
            ]

        self._inner.record_exception(
            exception,
            attributes=attributes,
            timestamp=timestamp,
            escaped=escaped,
        )

    def __enter__(self) -> "Span":
        return self

    def __exit__(
        self,
        exc_type: Optional[BaseException],
        exc_val: Optional[BaseException],
        exc_tb: Optional[types.TracebackType],
    ) -> None:
        if exc_val and self.is_recording():
            if self._inner._record_exception:
                self.record_exception(exception=exc_val, escaped=True)

            if self._inner._set_status_on_exception:
                self.set_status(
                    otel_trace_api.Status(
                        status_code=otel_trace_api.StatusCode.ERROR,
                        description=f"{exc_type.__name__}: {exc_val}",
                    ))

        super().__exit__(exc_type, exc_val, exc_tb)

    def __getattr__(self, name: str) -> Any:
        """Method allows to delegate method calls."""
        return getattr(self._inner, name)
