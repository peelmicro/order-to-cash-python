"""otc-cqrs: hand-rolled in-process dispatcher (application layer only)."""

from otc_cqrs.dispatcher import Dispatcher, HandlerRegistry
from otc_cqrs.errors import DispatcherValidationError, HandlerNotFoundError
from otc_cqrs.handlers import CommandHandler, EventHandler, QueryHandler
from otc_cqrs.messages import Command, Query

__all__ = [
    "Command",
    "CommandHandler",
    "Dispatcher",
    "DispatcherValidationError",
    "EventHandler",
    "HandlerNotFoundError",
    "HandlerRegistry",
    "Query",
    "QueryHandler",
]
