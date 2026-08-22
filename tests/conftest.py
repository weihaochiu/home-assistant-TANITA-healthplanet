"""Cross-platform test configuration with external sockets still blocked."""

from __future__ import annotations

import socket
import sys
from collections.abc import Callable

if sys.platform == "win32":
    # The HA pytest plugin allows Unix socketpairs but Windows implements
    # socketpair through loopback TCP. Preserve only that event-loop primitive;
    # pytest-socket continues to reject every test-created/external socket.
    _original_socket: Callable[..., socket.socket] = socket.socket

    def _local_event_loop_socketpair() -> tuple[socket.socket, socket.socket]:
        listener = _original_socket(socket.AF_INET, socket.SOCK_STREAM)
        client = _original_socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            client.connect(listener.getsockname())
            file_descriptor, _ = listener._accept()
            server = _original_socket(
                listener.family,
                listener.type,
                listener.proto,
                fileno=file_descriptor,
            )
        finally:
            listener.close()
        client.setblocking(False)
        server.setblocking(False)
        return server, client

    socket.socketpair = _local_event_loop_socketpair
