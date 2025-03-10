#!/usr/bin/env python3

import stat
import sys
import os
import signal
import socket
import time
import select
import tempfile
import subprocess

SCRIPT_LEN = int(sys.argv[2])
RUNTIME_LEN = int(sys.argv[3])
IMAGE_CHKSUM = sys.argv[4]


def unwrap_runtime(dst):
    self = sys.argv[1]
    ln_start = SCRIPT_LEN + 1
    ln_end = SCRIPT_LEN + RUNTIME_LEN
    os.system(f'sed -n \'{ln_start},{ln_end}p;{ln_end}q\' '
              f'\'{self}\' > \'{dst}\'')
    os.chmod(dst, stat.S_IRWXU | stat.S_IXGRP | stat.S_IXOTH)


def unwrap_image(dst):
    if os.path.exists(dst):
        return
    # TODO: container checksum
    self = sys.argv[1]
    ln_exclude = SCRIPT_LEN + RUNTIME_LEN
    os.system(f'sed \'1,{ln_exclude}d\' \'{self}\' > \'{dst}\'')


def get_ctrl_sock_addr():
    return os.path.join('/', 'tmp', f'exsif-{os.getuid()}')

def get_apptainer_path():
    # Find the system-installed apptainer using /usr/bin/env
    try:
        result = subprocess.run(['which', 'apptainer'], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None

def is_version_compatible(apptainer_path):
    # check if system apptainer is compatible
    try:
        result = subprocess.run([apptainer_path, '--version'], capture_output=True, text=True, check=True)
        version = result.stdout.strip()
        return True
        # actual version compatibility check
        # return version == '0.0.1'
    except subprocess.CalledProcessError:
        return False

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

        temp_rt_path = os.path.join(rt_dir, 'runtime')

        # DOUBLE CHECK: symlink system RT to tempdir if it exists
        system_rt_path = get_apptainer_path()
        if system_rt_path and is_version_compatible(system_rt_path):
            print(f'[DEBUG] Using system apptainer at {system_rt_path}')
            try:
                os.symlink(system_rt_path, temp_rt_path)  # uses system runtime
            except OSError as e:
                print('[ERROR] Failed to symlink system apptainer:', e)
                system_rt_path = None
        else:
            print('[DEBUG] System apptainer not found or incompatible')
            system_rt_path = None

        if not system_rt_path:
            unwrap_runtime(temp_rt_path)  # extract runtime

        # unwrap_runtime(os.path.join(rt_dir, 'runtime'))
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
                # Conn socket -> Disconnect the client
                else:
                    rlist.remove(sock)
                    sock.close()
                    print('[DEBUG] RT_DISCONNECT: num_clients = ',
                          len(rlist) - 1)
                    # Once refcnt reaches one (listenfd), terminate
                    if len(rlist) <= 1:
                        print('[DEBUG] RT_GOODBYE')
                        os.unlink(sock_addr)
                        return


def rt_client_main(sock_addr):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client_sock:
        client_sock.connect(sock_addr)
        # The fixed 256 byte len is probably fine here, since shm.h has it as well
        rt_path = client_sock.recv(256).decode(encoding='utf-8')
        rt_bin = os.path.join(rt_path, 'runtime')
        rt_img = os.path.join(rt_path, IMAGE_CHKSUM)
        unwrap_image(os.path.join(rt_img))
        args = ' '.join([f'"{x}"' for x in sys.argv[5:]])
        ret = os.system(f'"{rt_bin}" run "{rt_img}" {args}')
        sys.exit(ret)


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
sys.exit(0)
