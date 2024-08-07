"""Contains the pubsub manager and the pubsub functions."""

from __future__ import annotations

import re
import typing

if typing.TYPE_CHECKING:  # pragma: no cover
    from typing_extensions import TypeAlias
else:
    try:
        from typing import TypeAlias as TypeAlias
    except ImportError:
        try:
            from typing_extensions import TypeAlias as TypeAlias
        except ImportError:
            TypeAlias = None

import celery

__all__ = [
    "publish",
    "publish_now",
    "subscribe",
    "subscribe_to",
    "unsubscribe",
]
from celery import Task, group
from celery.result import AsyncResult, EagerResult

PA: TypeAlias = typing.Any  # ParamSpec args
PK: TypeAlias = typing.Any  # ParamSpec kwargs
P: TypeAlias = typing.Any  # ParamSpec
R: TypeAlias = typing.Any  # Return type

task: typing.Callable[
    ..., typing.Callable[[typing.Callable[[P], R]], Task[P, R]]
] = celery.shared_task


class PubSubManager:
    def __init__(self) -> None:
        super(PubSubManager, self).__init__()
        self.subscribed: set[tuple[str, re.Pattern[str], Task[P, R]]] = set()
        self.jobs: dict[str, group] = {}
        self.enabled = True

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def publish(self, topic: str, *args: PA, **kwargs: PK) -> AsyncResult[R]:
        if not self.enabled:
            return celery.group([]).delay()
        result = self.get_jobs(topic).delay(*args, **kwargs)
        return result

    def publish_now(self, topic: str, *args: PA, **kwargs: PK) -> EagerResult[R]:
        if not self.enabled:
            return celery.group([]).apply()
        # Ignoring type because of this: https://github.com/sbdchd/celery-types/issues/111
        result = self.get_jobs(topic).apply(args=args, kwargs=kwargs)  # type: ignore
        return result

    def subscribe(self, topic: str, task: Task[P, R]) -> None:
        key = (topic, self._topic_to_re(topic), task)
        if key not in self.subscribed:
            self.subscribed.add(key)
            self.jobs = {}

    def unsubscribe(self, topic: str, task: Task[P, R]) -> None:
        key = (topic, self._topic_to_re(topic), task)
        if key in self.subscribed:
            self.subscribed.discard(key)
            self.jobs = {}

    def get_jobs(self, topic: str) -> group:
        if topic not in self.jobs:
            self._gen_jobs(topic)
        return self.jobs[topic]

    def _gen_jobs(self, topic: str) -> None:
        jobs = []
        for job in self.subscribed:
            if job[1].match(topic):
                jobs.append(job[2].s())
        self.jobs[topic] = celery.group(jobs)

    @staticmethod
    def _topic_to_re(topic: str) -> re.Pattern[str]:
        assert isinstance(topic, str)
        re_topic = topic.replace(".", r"\.").replace("*", r"[^.]+").replace("#", r".+")
        return re.compile(r"^{}$".format(re_topic))


_pubsub_manager: PubSubManager = PubSubManager()


def subscribe_to(topic: str) -> typing.Callable[[typing.Callable[[P], R]], Task[P, R]]:
    def decorator(func: typing.Callable[[P], R]) -> Task[P, R]:
        if isinstance(func, Task):
            task_instance: Task[P, R] = func
        else:
            app_name, module_name = func.__module__.split(".", 1)
            task_name = f"{app_name}.{module_name}.{func.__qualname__}"
            task_instance = task(name=task_name)(func)
        _pubsub_manager.subscribe(topic, task_instance)
        return task_instance

    return decorator


def publish(topic: str, *args: PA, **kwargs: PK) -> AsyncResult[R]:
    return _pubsub_manager.publish(topic, *args, **kwargs)


def publish_now(topic: str, *args: PA, **kwargs: PK) -> EagerResult[R]:
    return _pubsub_manager.publish_now(topic, *args, **kwargs)


def subscribe(topic: str, task: Task[P, R]) -> None:
    return _pubsub_manager.subscribe(topic, task)


def unsubscribe(topic: str, task: Task[P, R]) -> None:
    return _pubsub_manager.unsubscribe(topic, task)

def set_enabled(enabled: bool) -> None:
    _pubsub_manager.set_enabled(enabled)
