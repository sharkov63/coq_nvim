from asyncio.events import Handle, get_running_loop
from typing import Any, Mapping, Optional

from pynvim.api.nvim import Nvim
from pynvim_pp.api import buf_filetype, buf_name, cur_buf

from ...registry import autocmd, enqueue_event, rpc
from ..runtime import Stack


@rpc(blocking=True)
def _dir_changed(nvim: Nvim, stack: Stack, event: Mapping[str, Any]) -> None:
    cwd: str = event["cwd"]
    stack.state.cwd = cwd


autocmd("DirChanged") << f"lua {_dir_changed.name}(vim.v.event)"


@rpc(blocking=True)
def _ft_changed(nvim: Nvim, stack: Stack) -> None:
    buf = cur_buf(nvim)
    name = buf_name(nvim, buf=buf)
    ft = buf_filetype(nvim, buf=buf)
    stack.db.ft_update(name, filetype=ft)


autocmd("FileType") << f"lua {_ft_changed.name}()"


@rpc(blocking=True)
def _insert_enter(nvim: Nvim, stack: Stack) -> None:
    stack.state.inserting = True


autocmd("InsertEnter") << f"lua {_insert_enter.name}()"


@rpc(blocking=True)
def _insert_leave(nvim: Nvim, stack: Stack) -> None:
    stack.state.inserting = False


autocmd("InsertLeave") << f"lua {_insert_leave.name}()"


@rpc(blocking=True)
def _vaccum(nvim: Nvim, stack: Stack) -> None:
    stack.db.vaccum()


_handle: Optional[Handle] = None


@rpc(blocking=True)
def _cursor_hold(nvim: Nvim, stack: Stack) -> None:
    global _handle
    if _handle:
        _handle.cancel()

    def cont() -> None:
        enqueue_event(_vaccum)

    loop = get_running_loop()
    _handle = loop.call_later(0.5, cont)


autocmd("CursorHold", "CursorHoldI") << f"lua {_cursor_hold.name}()"

