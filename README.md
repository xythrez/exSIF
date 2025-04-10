EXSIF Build Tools
=================

This repo contains all scripts and components needed to build an exSIF image
from it's original SIF counterpart.

Build Requirements
------------------

The following components are required on the system building the image file:

1. Apptainer 
2. Python 3.6+
3. An apptainer SIF file or DEF file

Since Apptainer only works on Linux, a Linux environment is needed to build
the container.

Run Requirements
----------------

The following components are needed to run a exsif container:

1. Python 3.6+
2. GNU Coreutils

As both these components are found on all common Enterprise Linux distributions,
the exSIF format can run on almost all Linux systems.


Building a Container
--------------------

1. Build a standard SIF container by following the standard instructions
[here](https://apptainer.org/docs/user/main/cli/apptainer_build.html). If you
are basing your container off of docker, you can also directly
[pull from dockerhub](https://apptainer.org/docs/user/main/build_a_container.html).

2. Run the script `./make_exsif <input.sif> <output.exsif>`

Running a Container
-------------------

To run an exsif container

1. Mark the container file as executable `chmod +x ./container.exsif`

2. Invoke the container directly `./container.exsif`

This should start a local runtime and drop the user into the container session

License
-------------------
This project is licensed under the [MIT License](./LICENSE).
