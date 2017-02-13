# Install ![GitHub Downloads][downloads-status]
King Phisher Server is only supported on Linux. King Phisher Client is supported on Windows and Linux.

Installing King Phisher is easy.
For Windows Download the [Latest Release Here][releases]

For quick install on [Supported Linux Operating Systems][operating-systems]
```bash
wget -q https://github.com/securestate/king-phisher/raw/master/tools/install.sh && sudo bash ./install.sh
```
Visit the [wiki][wiki] or watch a [how to videos][videos] while you wait for the install complete.

The one liner install will install King Phisher to `/opt/king-phisher`.

### Advanced Install Options
Just the King Phisher Client
```bash
cd /opt/
sudo git clone https://github.com/securestate/king-phisher.git
cd king-phisher 
sudo tools/install.sh --skip-server
# get a cup of coffee this going to take a minute
```

Just the King Phisher Server
```bash
cd /opt/
sudo git clone https://github.com/securestate/king-phisher.git
cd king-phisher 
sudo tools/install.sh --skip-client # Highly recommended Yes for Postgres install
# get a cup of coffee this going to take a minute
```

Both
```bash
cd /opt/
sudo git clone https://github.com/securestate/king-phisher.git
cd king-phisher 
sudo tools/install.sh # Highly recommended Yes for Postgres install
# get a cup of coffee this going to take a minute
```

## Quick Links for Important Information
- [Supported Linux Operating Systems][operating-systems]
- [Minimum System Requirements][minimum-req]
- [README][readme]
- [Bleeding Edge as a Beta Tester][beta-testing]

## Overview
The King Phisher Server is only supported on Linux. The King Phisher
Client is supported on both Windows and Linux. Windows executables are
available from the [releases page][releases].

An installation script is available to automate the process on supported
versions of Linux. Instructions on how it can be used are
[Linux Install Steps](#linux-install-steps) section. It is highly recommended
that users ensure that the system clock and timezone are set accurately on both
the client and server.

King Phisher uses a client server architecture. The ```KingPhisherServer```
application runs as a daemon on the phishing server. The ```KingPhisher```
client file is meant to connect to the daemon over SSH from a remote system. The
server must be running SSH and allow ports to be forwarded. The client after
connecting, communicates via RPC to the server through the encrypted SSH tunnel.

Additionally, the user logging in with the King Phisher Client will require a
valid local account on the King Phisher Server. The King Phisher Server provides
its own HTTP server and does not require an additional one such as Apache, or
Nginx. Running an additional server such as Apache or Nginx will likely result
in a conflict in when trying to bind to a default port.

## Linux Install Steps

The following steps walk through installing King Phisher on Linux into a
self contained directory. Installing King Phisher into ```/opt/king-phisher```
is recommended.

King Phisher comes with an install script for a convenient installation process.
It will handle installing all of the operating system dependencies, the required
Python packages, and basic configuration. The automated install scripts supports
a limited set of Linux flavors. To request that one be added, please open a
support ticket.

After cloning the repository run the install.sh script that is in the tools
directory as such: ```sudo tools/install.sh```. This will download all the
required packages and set up a default server configuration. The automated
installation process may take up to 20 minutes to complete depending on
the speed at which packages are downloaded.

**WARNING:** If installing the server component of King Phisher, the automated
install script will use the template configuration file which specifies SQLite
as the database backend. It is highly recommended that PostgreSQL be used over
SQLite to support future database upgrades. For more information on selecting
and configuring a database backend, please see the
[wiki][wiki].

### Install Script Supported Flavors
| Linux Flavor | Client Support | Server Support |
|:-------------|:--------------:|:--------------:|
| BackBox      | yes            | yes            |
| CentOS       | no             | yes            |
| Debian       | yes            | yes            |
| Fedora       | yes            | yes            |
| Kali         | yes            | yes            |
| Ubuntu       | yes            | yes            |

### Install Script Options
The installation script supports a number of command line options. The latest of
which can be viewed by running `tools/install.sh --help`. These options can be
used to (for example) install King Phisher client or server components from
another automation tool such as Ansible.

#### Install Script Environment Variables
Certain environment variables can also be set to change the default behaviour of
the installation script. Command line options take priority over environment
variables.

| Variable Name               | Description                       | Default           |
|:----------------------------|:----------------------------------|:-----------------:|
| KING\_PHISHER\_DIR          | The base directory to install to  | /opt/king-phisher |
| KING\_PHISHER\_SKIP\_CLIENT | Skip installing client components | **NOT SET**       |
| KING\_PHISHER\_SKIP\_SERVER | Skip installing server components | **NOT SET**       |

Variables which are not set by default are flags which are toggled when defined.
For example to skip installing client components the following command could be
used: ```KING_PHISHER_SKIP_CLIENT=x tools/install.sh```

### Recommended Minimum Requirements
It is recommended that King Phisher be run on a system which exceeds the host
operating systems minimum requirements. At this time a minimum of 2048 MB of RAM
and at least a CPU with 2 cores running at 1.5 GHz is sufficient. Furthermore
the hard disk should have additional space on top of the host OS recommendations
for the installation of required packages. For the client it is recommended that
the display support a minimum resolution of 1024x800.

Recommended Linux Flavors:
 * King Phisher Server - [Ubuntu Server LTS](http://www.ubuntu.com/download/server)
 * King Phisher Client - [Ubuntu GNOME](https://ubuntugnome.org/download/)

## Other Linux Versions
Install each of the required packages with
```pip install -r requirements.txt```. If any fail to install they are most
likely missing libraries that will need to be installed through the native
package manager.

## Required Python Packages
All required packages are listed in the provided ```requirements.txt``` file to
be easily installed with pip. Some packages may not install correctly due to
missing native libraries. The automated install script will handle the
installation of these libraries for the supported flavors of Linux.


[beta-testing]: https://github.com/securestate/king-phisher/wiki/Updating-King-Phisher#beta-testing
[downloads-status]: https://img.shields.io/github/downloads/securestate/king-phisher/total.svg?style=flat-square
[minimum-req]: https://github.com/securestate/king-phisher/blob/installmd_update/INSTALL.md#recommended-minimum-requirements
[operating-systems]: https://github.com/securestate/king-phisher/blob/installmd_update/INSTALL.md#install-script-supported-flavors
[readme]: https://github.com/securestate/king-phisher/blob/master/README.md
[releases]: https://github.com/securestate/king-phisher/releases
[videos]: https://securestate.wistia.com/projects/laevqz2p29
[wiki]: https://github.com/securestate/king-phisher/wiki