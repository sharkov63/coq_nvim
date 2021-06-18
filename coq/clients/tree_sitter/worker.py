from concurrent.futures import Future, InvalidStateError, TimeoutError
from contextlib import suppress
from pathlib import Path
from threading import Lock
from typing import Any, Iterator, MutableMapping, Sequence, Tuple
from uuid import UUID, uuid4

from pynvim_pp.lib import threadsafe_call

from ...shared.runtime import Supervisor
from ...shared.runtime import Worker as BaseWorker
from ...shared.settings import BaseClient
from ...shared.types import Completion, Context, Edit, WTF8Pos

_LUA = (Path(__file__).resolve().parent / "request.lua").read_text("UTF-8")


class Worker(BaseWorker[BaseClient, None]):
    def __init__(self, supervisor: Supervisor, options: BaseClient, misc: None) -> None:
        self._lock = Lock()
        self._sessions: MutableMapping[UUID, Future] = {}
        supervisor.nvim.api.exec_lua(_LUA, ())
        super().__init__(supervisor, options=options, misc=misc)

    def _req(self, session: UUID, pos: WTF8Pos) -> Any:
        token = uuid4()
        fut: Future = Future()

        with self._lock:
            self._sessions[token] = fut

        def cont() -> None:
            self._supervisor.nvim.api.exec_lua(
                "COQts_req(...)", (str(token), str(session), pos)
            )

        threadsafe_call(self._supervisor.nvim, cont)

        try:
            ret = fut.result(timeout=self._supervisor.options.timeout)
        except TimeoutError:
            ret = None

        with self._lock:
            if token in self._sessions:
                self._sessions.pop(token)
        return ret

    def notify(self, token: UUID, msg: Sequence[Any]) -> None:
        with self._lock:
            if token in self._sessions:
                reply, *_ = msg
                with suppress(InvalidStateError):
                    self._sessions[token].set_result(reply)

    def work(self, context: Context) -> Iterator[Sequence[Completion]]:
        cmp = Completion(
            source=self._options.short_name,
            primary_edit=Edit(new_text="TODO"),
        )
        yield ()

