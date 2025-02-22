#!/usr/bin/env python3


import sys
import os
import signal
import socket
import time
import select
import tempfile


def get_ctrl_sock_addr():
    return os.path.join('/', 'tmp', f'exsif-{os.getuid()}')


def rt_ctrl_server_main(sock_addr):
    # Remove any lingering sockets
    try:
        os.unlink(sock_addr)
    except OSError:
        pass

    with (socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as ctrl_sock,
          tempfile.TemporaryDirectory(prefix='exsif-') as rt_dir):
        ctrl_sock.bind(sock_addr)
        ctrl_sock.listen()
        # TODO: Unwrap the RT, or symlink system RT to tempdir
        rlist = {ctrl_sock}
        while True:
            rready, _, _ = select.select(rlist, [], [])
            for sock in rready:
                # Listen socket -> Add connection to monitor list
                if sock == ctrl_sock:
                    conn_sock = sock.accept()[0]
                    conn_sock.send(bytes(rt_dir, encoding='utf-8'))
                    rlist.add(conn_sock)
                    print('[DEBUG] RT_CONNECT: num_clients =', len(rlist) - 1)
                else:
                    rlist.remove(sock)
                    print('[DEBUG] RT_DISCONNECT: num_clients = ',
                          len(rlist) - 1)
                    # Once refcnt reaches one (listenfd), terminate
                    if len(rlist) <= 1:
                        print('[DEBUG] RT_GOODBYE')
                        return


def rt_client_main(sock_addr):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client_sock:
        client_sock.connect(sock_addr)
        # The fixed 256 byte len is probably fine here, since shm.h has it as well
        rt_path = client_sock.recv(256).decode(encoding='utf-8')
        # TODO: check and extract container, then spawn subprocess using rt_path and container
        print(rt_path)
        while True:
            time.sleep(1)



def main():
    sock_addr = get_ctrl_sock_addr()
    # Try connecting to the server first, if we fail we start a new rt
    try:
        rt_client_main(sock_addr)
        return
    except IOError:
        pass

    # Fork off a rt daemon
    if os.fork() == 0:
        print('[INFO] Starting new RT daemon')
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        os.setpgrp()
        rt_ctrl_server_main(sock_addr)
        return

    # I am too lazy to use sigwaitinfo here.
    # FIXME: If we get a race condition, do this properly
    time.sleep(0.01)

    # Retry connecting to the server
    try:
        rt_client_main(sock_addr)
        return
    except IOError as err:
        print('[ERROR] Failed to connect to RT daemon')
        pass


if __name__ == '__main__':
    main()
