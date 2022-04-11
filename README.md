# Open CAS Linux

[![Build Status](https://d1rxsi9lvcwnz5.cloudfront.net/master-status/ocl/build/curr-badge.svg)](https://d1rxsi9lvcwnz5.cloudfront.net/master-status/ocl/build/build.html)
[![Tests Status](https://d1rxsi9lvcwnz5.cloudfront.net/master-status/ocl/tests/curr-badge.svg)](https://d1rxsi9lvcwnz5.cloudfront.net/master-status/ocl/tests/tests.html)
[![Coverity status](https://scan.coverity.com/projects/19084/badge.svg)](https://scan.coverity.com/projects/open-cas-open-cas-linux)
[![License](https://d1rxsi9lvcwnz5.cloudfront.net/master-status/license-badge.svg)](LICENSE)

Open CAS  accelerates Linux applications by caching active (hot) data to
a local flash device inside servers. Open CAS implements caching at the
server level, utilizing local high-performance flash media as the cache drive
media inside the application server as close as possible to the CPU, thus
reducing storage latency as much as possible.
The Open Cache Acceleration Software installs into the GNU/Linux operating
system itself, as a kernel module. The nature of the integration provides a
cache solution that is transparent to users and  applications, and your
existing storage infrastructure. No storage migration effort or application
changes are required.

Open CAS is distributed on BSD-3-Clause license (see
https://opensource.org/licenses/BSD-3-Clause for full license texts).

Open CAS uses Safe string library (safeclib) that is MIT licensed.

## Installation

We recommend using the latest version, which contains all the important fixes
and performance improvements. Bugfix releases are guaranteed only for the
latest major release line (currently 22.3.x).

To download the latest Open CAS Linux release run following commands:

```
wget https://github.com/Open-CAS/open-cas-linux/releases/download/v22.3/open-cas-linux-22.03.0.0666.release.tar.gz
tar -xf open-cas-linux-22.03.0.0666.release.tar.gz
cd open-cas-linux-22.03.0.0666.release/
```

Alternatively, if you want recent development (unstable) version, you can clone GitHub repository:

```
git clone https://github.com/Open-CAS/open-cas-linux
cd open-cas-linux
git submodule update --init
```

### Source compile and install

To install all required python packages run the following command:

```
python3 -m pip install -r requirements.txt
```

To configure, build and install Open CAS Linux run following commands:

```
./configure
make
make install
```

The `./configure` performs check for dependencies, so if some of them are missing,
command will print their names in output. After installing missing dependencies
you need to run `./configure` once again - this time it should succeed.

> NOTE: If after installing CAS, your system boots into emergency mode due to the
> **"Failed to start opencas initialization service."** error, you need to force SELinux
> relabelling in permissive mode on your filesystem.\
> Refer to the [Open CAS documentation](https://open-cas.github.io/guide_running.html#rebooting-power-cycling-and-open-cas-linux-autostart) for details.

### RPM/DEB install

Alternatively, you can generate RPM/DEB packages from downloaded sources and
install those packages instead. To do so, simply run:

__on RPM based systems:__
```
make rpm
rm -f packages/*debug*
dnf install ./packages/open-cas-linux*.rpm
```

__on DEB based systems:__
```
make deb
apt install ./packages/open-cas-linux*.deb
```

Package generating script will inform you of any missing dependencies.
You can find detailed instructions in the [Open CAS documentation](https://open-cas.github.io/guide_installing.html#creating-rpmdeb-packages)

## Getting Started

To quickly deploy Open CAS Linux in your system please follow the instructions
available [here](https://open-cas.github.io/getting_started_open_cas_linux.html).

## Documentation

The complete documentation for Open CAS Linux is available in the
[Open CAS Linux Administration Guide](https://open-cas.github.io/guide_introduction.html).

## Running Tests

Before running tests make sure you have a platform with at least 2 disks (one for cache and one for core). Be careful as these devices will be most likely overwritten with random data during tests. Tests can be either executed locally or on a remote platform (via ssh) specified in the dut_config.

1. Go to test directory `cd test/functional`.
1. Install dependencies with command `pip3 install -r test-framework/requirements.txt`.
1. Create DUT config. See example [here](test/functional/config/example_dut_config.yml).
    a) Set disks params. You need at least two disks, of which at least one is an SSD drive.
    b) For remote execution uncomment and set the `ip`, `user` and `password` fields.
    c) For local execution just leave these fields commented.
1. Run tests using command `pytest-3 --dut-config=<CONFIG>` where `<CONFIG>` is path to your config file, for example `pytest-3 --dut-config="config/dut_config.yml"`.

## Security

To report a potential security vulnerability please follow the instructions
[here](https://open-cas.github.io/contributing.html#reporting-a-potential-security-vulnerability).
