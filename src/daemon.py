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
import hashlib
import re

# Constants representing script and runtime segment lengths
SCRIPT_LEN = int(sys.argv[2])
RUNTIME_LEN = int(sys.argv[3])
IMAGE_CHKSUM = sys.argv[4]

def calculate_checksum(file_path):
    # Compute the SHA-256 checksum of a given file
    hasher = hashlib.sha256()
    with open(file_path, 'rb') as f:
        hasher.update(f.read())
    return hasher.hexdigest()

def unwrap_runtime(dst):
    # Extract the runtime portion of the script and store it in the destination file
    self = sys.argv[1]
    ln_start = SCRIPT_LEN + 1
    ln_end = SCRIPT_LEN + RUNTIME_LEN
    os.system(f'sed -n \'{ln_start},{ln_end}p;{ln_end}q\' '
              f'\'{self}\' > \'{dst}\'')
    os.chmod(dst, stat.S_IRWXU | stat.S_IXGRP | stat.S_IXOTH) # Set execute permissions


def unwrap_image(dst):
    # Extract the image only if it doesn't exist or has an outdated checksum
    if os.path.exists(dst) and calculate_checksum(dst) == IMAGE_CHKSUM:
        return  # Skip extraction if the file is up to date
    
    self = sys.argv[1]
    ln_exclude = SCRIPT_LEN + RUNTIME_LEN
    os.system(f'sed \'1,{ln_exclude}d\' \'{self}\' > \'{dst}\'') # Set execute permissions

def get_ctrl_sock_addr():
    # Generate the path for the control socket based on the user ID
    return os.path.join('/', 'tmp', f'exsif-{os.getuid()}')

def get_apptainer_path():
    # Find the path of the system-installed apptainer binary
    try:
        result = subprocess.run(['command', '-v', 'apptainer'], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None  # Return None if apptainer is not found

def is_version_compatible(apptainer_path):
    # Check if the installed apptainer version is compatible
    try:
        result = subprocess.run([apptainer_path, '--version'], capture_output=True, text=True, check=True)
        version = result.stdout.strip()
        print(f'[DEBUG] System apptainer version: {version}')
        
        # Ensure version starts with 'apptainer version 1.3.x'
        if re.match(r'^apptainer version 1\.3\.\d+', version):
            return True
    except subprocess.CalledProcessError:
        return False  # Return False if the version check fails

def rt_ctrl_server_main(sock_addr):
    # Main function for the runtime control server
    try:
        os.unlink(sock_addr)  # Remove any lingering socket files
    except OSError:
        pass

    with (socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as ctrl_sock,
          tempfile.TemporaryDirectory(prefix='exsif-') as rt_dir):
        ctrl_sock.bind(sock_addr)
        ctrl_sock.listen()

        temp_rt_path = os.path.join(rt_dir, 'runtime')

        # Attempt to use system-installed runtime if available
        system_rt_path = get_apptainer_path()
        print("[DEBUG] what's the system_rt_path", system_rt_path)
        if system_rt_path and is_version_compatible(system_rt_path):
            print(f'[DEBUG] Using system apptainer at {system_rt_path}')
            try:
                os.symlink(system_rt_path, temp_rt_path)  # Use system runtime
            except OSError as e:
                print('[ERROR] Failed to symlink system apptainer:', e)
                system_rt_path = None
        else:
            print('[DEBUG] System apptainer not found or incompatible')
            system_rt_path = None

        if not system_rt_path:
            unwrap_runtime(temp_rt_path)  # Extract runtime if system one is unavailable

        rlist = {ctrl_sock}
        while True:
            rready, _, _ = select.select(rlist, [], [])
            for sock in rready:
                if sock == ctrl_sock:  # New client connection
                    conn_sock = sock.accept()[0]
                    conn_sock.send(bytes(rt_dir, encoding='utf-8'))
                    rlist.add(conn_sock)
                    print('[DEBUG] RT_CONNECT: num_clients =', len(rlist) - 1)
                else:  # Handle client disconnection
                    rlist.remove(sock)
                    sock.close()
                    print('[DEBUG] RT_DISCONNECT: num_clients = ', len(rlist) - 1)
                    if len(rlist) <= 1:  # Shutdown server if no more clients remain
                        print('[DEBUG] RT_GOODBYE')
                        os.unlink(sock_addr)
                        return

def rt_client_main(sock_addr):
    # Main function for the runtime client, responsible for connecting to the control server
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client_sock:
        client_sock.connect(sock_addr)
        # The fixed 256 byte len is probably fine here, since shm.h has it as well
        rt_path = client_sock.recv(256).decode(encoding='utf-8')
        rt_bin = os.path.join(rt_path, 'runtime')
        rt_img = os.path.join(rt_path, IMAGE_CHKSUM)
        unwrap_image(os.path.join(rt_img))  # Ensure the runtime image is available
        args = ' '.join([f'"{x}"' for x in sys.argv[5:]])  # Prepare arguments
        ret = os.system(f'"{rt_bin}" run "{rt_img}" {args}')  # Execute the extracted runtime
        sys.exit(ret)

def main():
    # Main function that attempts to connect to an existing runtime server or starts a new one
    sock_addr = get_ctrl_sock_addr()
    try:
        rt_client_main(sock_addr)  # Attempt to connect to an existing runtime
        return
    except IOError:
        pass  # If no existing server is found, start a new one

    if os.fork() == 0:  # Fork a new runtime daemon
        print('[INFO] Starting new RT daemon')
        signal.signal(signal.SIGHUP, signal.SIG_IGN)  # Ignore SIGHUP to avoid termination
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
