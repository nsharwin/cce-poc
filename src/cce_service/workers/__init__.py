"""Async worker pool that drains the job queue into the dispatcher."""

from cce_service.workers.consumer import JobConsumer

__all__ = ["JobConsumer"]
