import asyncio
import logging
import socket
import sys
import os

from . import protocol

logger = logging.getLogger(__name__)


def send_directive(directive, recipient, payload, socket_path):
    if payload == '-':
        payload = sys.stdin.read()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(socket_path)
    sock.sendall(f"{recipient}\n{directive}\n{payload}".encode('utf-8') + protocol.DELIM)
    response = b''
    while True:
        response = sock.recv(4096)
        sys.stdout.buffer.write(response + b"\n")
        sys.stdout.flush()

# FIXME: the socket path is in the config, it shouldn't need to be passed as an arg here
def mainloop(receptor, socket_path, loop=asyncio.get_event_loop()):
    config = receptor.config
    listener = loop.create_server(
        lambda: protocol.BasicProtocol(receptor, loop),
        config.controller_listen_address, config.controller_listen_port, ssl=config.get_server_tls_context())
    logger.info("Serving on %s:%s", config.controller_listen_address, config.controller_listen_port)
    loop.create_task(listener)
    control_listener = loop.create_unix_server(
        lambda: protocol.BasicControllerProtocol(receptor, loop),
        path=socket_path
    )
    logger.info(f'Opening control socket on {socket_path}')
    loop.create_task(control_listener)
    loop.create_task(receptor.watch_expire())
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.stop()
        os.remove(socket_path)
