import json
import queue
import threading
from typing import Any, Dict, Generator, Iterable, Optional, Set


class EventBus:
    """In-memory Server-Sent Events pub/sub broker keyed by user_id."""

    def __init__(self):
        self._lock = threading.Lock()
        # user_id -> set of (client_id, queue.Queue)
        self._subscribers: Dict[int, Set[tuple]] = {}

    def publish_users(
        self,
        user_ids: Iterable[int],
        event: str,
        data: Dict[str, Any],
        exclude_client_id: Optional[str] = None,
    ) -> None:
        msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        targets = set(int(uid) for uid in user_ids if uid is not None)
        if not targets:
            return

        with self._lock:
            queues = []
            for uid in targets:
                for cid, q in self._subscribers.get(uid, ()):
                    if exclude_client_id and cid == exclude_client_id:
                        continue
                    queues.append(q)

        for q in queues:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

    def publish_all(
        self,
        event: str,
        data: Dict[str, Any],
        exclude_client_id: Optional[str] = None,
    ) -> None:
        msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        with self._lock:
            queues = [
                q
                for subs in self._subscribers.values()
                for cid, q in subs
                if not (exclude_client_id and cid == exclude_client_id)
            ]

        for q in queues:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

    def subscribe(self, user_id: int, client_id: str = '') -> Generator[str, None, None]:
        q: queue.Queue = queue.Queue(maxsize=128)
        entry = (client_id or '', q)
        uid = int(user_id)

        with self._lock:
            self._subscribers.setdefault(uid, set()).add(entry)

        try:
            yield 'retry: 5000\n\n'
            yield f'event: connected\ndata: {json.dumps({"user_id": uid, "client_id": client_id})}\n\n'
            while True:
                try:
                    msg = q.get(timeout=20)
                    yield msg
                except queue.Empty:
                    yield ': ping\n\n'
        finally:
            with self._lock:
                subs = self._subscribers.get(uid)
                if subs:
                    subs.discard(entry)
                    if not subs:
                        self._subscribers.pop(uid, None)


EVENTS = EventBus()
