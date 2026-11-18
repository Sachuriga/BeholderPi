![BeholderPi logo](docs/images/BeholderPiLogo.svg.png "BeholderPI logo")

# BeholderPi

A scalable array of networked Raspberry Pi cameras that stream to one recording PC.

- low cost, roughly 100–200 Euro per camera node
- 800x600 at 30 fps, visible light or IR
- low-latency preview of the merged views
- cameras synchronized to sub-millisecond resolution
- hardware-accelerated encoding on the PC
- synchronization with external systems such as electrophysiology recordings

Built on Picamera, ZMQ, OpenCV and FFmpeg.

This README is the complete installation guide for the camera side (the *eyes* and the *spectator*). It was written
from an installation carried out on the lab PC on 2026-11-18. A Chinese version of the same procedure is in
[docs/Installation_Walkthrough_zh.md](docs/Installation_Walkthrough_zh.md).

What was verified on that day, and what was not:

- Sections 3 to 8 were carried out on real hardware: two eyes and one spectator were installed and checked.
- The two scripts in `scripts/setup/` and `ansible/install_eye.yml` were fixed afterwards for the problems listed in
  section 9. The fixed versions passed a syntax check but have not been run end to end. If a script behaves differently
  from this guide, use the manual fix given in section 9.
- Section 7 (starting `beholder`) describes the command line as defined in the code; it was not run on that day.

## Contents

1. [Hardware](#1-hardware)
2. [How the system is laid out](#2-how-the-system-is-laid-out)
3. [One-time preparation of the PC](#3-one-time-preparation-of-the-pc)
4. [Flashing an SD card](#4-flashing-an-sd-card)
5. [Installing an eye](#5-installing-an-eye)
6. [Installing the spectator](#6-installing-the-spectator)
7. [Checking the whole system and starting beholder](#7-checking-the-whole-system-and-starting-beholder)
8. [Adding or reinstalling an eye later](#8-adding-or-reinstalling-an-eye-later)
9. [Troubleshooting](#9-troubleshooting)
10. [Command reference](#10-command-reference)
11. [Repository layout and further documents](#11-repository-layout-and-further-documents)
12. [Credits](#12-credits)

## 1. Hardware

- [Raspberry Pi 3B+ or 4B](https://www.raspberrypi.org/documentation/hardware/raspberrypi/README.md), one per camera
  plus one for the spectator
- [Picamera-compatible camera module](https://www.raspberrypi.org/documentation/hardware/camera/README.md), for example
  Camera Module v2 (8 MP, FOV 62.2° horizontal, 48.8° vertical). Background reading:
  [how the PiCamera works](https://picamera.readthedocs.io/en/release-1.13/fov.html)
- [PoE HAT](https://www.raspberrypi.org/products/poe-hat/) and a PoE switch, if the Pis are powered over ethernet
- one SD card per Pi (the image is 2 GB; 32 GB cards were used)
- a receiving PC, ideally one CPU core per camera, with two network interfaces: one for the internet and one wired
  port for the camera network
- optionally a GPU with hardware video encoding

## 2. How the system is laid out

All devices sit on one isolated wired network, `10.0.0.0/24`.

| Device | Hostname | Address | Job |
|---|---|---|---|
| Recording PC | beholder | `10.0.0.11` | Receives the streams, shows the preview, records. It is also the **time source** for every Pi (chrony) |
| One Pi | spectator | `10.0.0.1` | DHCP server of the camera network. Hands each eye its address based on the eye's hostname |
| Camera Pi | `eyeNN` | `10.0.0.1NN` | Captures frames and publishes them on TCP port 5555. `eye02` is at `10.0.0.102` |

Things that are true throughout this guide:

- **Every SD card gets the same image.** Whether a Pi becomes an eye or the spectator is decided by which install
  script is run after it boots.
- **Install all eyes first and the spectator last.** Once the spectator takes over, the camera network has no internet
  access, and an eye that is not finished can no longer download packages.
- **The PC's wired port has two modes.** During installation it is in NetworkManager's `shared` mode: the PC hands out
  addresses and forwards the Pis to the internet. In normal operation it has the fixed address `10.0.0.11` and the
  spectator hands out addresses.
- **The hostname decides the image orientation.** The default eye configuration flips the picture vertically and
  horizontally for `eye07` to `eye12` and leaves `eye01` to `eye06` unflipped
  (`piEye/resources/config_pieye_default.yml`).
- **The eyes run upstream code.** The eye playbook clones `wonkoderverstaendige/BeholderPi` onto each Pi. Changes made
  to `piEye/` in a fork do not reach the Pis on their own.
- **All commands run on the Linux PC**, from the repository root (`~/BeholderPi` on the lab PC).

The SSH command for the Pis is long. Define this alias in every new terminal; the rest of the guide uses it:

```bash
alias pissh='ssh -i ~/.ssh/id_beholderpi -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR'
```

## 3. One-time preparation of the PC

Installing the `beholder` software itself (conda environment, FFmpeg with NVENC) is described in
[docs/Installation_Beholder.md](docs/Installation_Beholder.md). The steps below are what the camera side needs.

### 3.1 SSH key

```bash
ls ~/.ssh/id_beholderpi || ssh-keygen -t ed25519 -f ~/.ssh/id_beholderpi -C "BeholderPi keys"
```

Leave the passphrase empty; ansible needs a key it can use unattended.

**Back up `~/.ssh/id_beholderpi` and `~/.ssh/id_beholderpi.pub`.** The image only contains the public key and has SSH
password login switched off. A Pi installed with one key rejects any other key with `Permission denied (publickey)`,
and the only way back in is to reflash it.

### 3.2 Let the PC serve time to the camera network

The eyes and the spectator synchronize their clocks to `10.0.0.11`. By default chrony answers no other machine, so it
has to be allowed explicitly:

```bash
printf 'allow 10.0.0.0/24\nlocal stratum 10\n' | sudo tee /etc/chrony/conf.d/beholder.conf
sudo systemctl restart chrony
```

- `allow 10.0.0.0/24` lets machines on the camera network query this PC.
- `local stratum 10` keeps the PC serving time when it has no internet connection itself, so the cameras stay
  consistent with each other.

No script creates this file. Add it again after reinstalling the PC's operating system.

### 3.3 Make sure the wired port can hold a truly static address

On an Ubuntu installation that left a `/etc/netplan/50-cloud-init.yaml` behind, that file sets `dhcp4: true` for the
wired interface. NetworkManager's own file for the connection does not mention `dhcp4`, so after the two are merged the
port stays on DHCP *in addition to* its static address. `nmcli` then reports `auto` although `manual` was set, and the
port only comes up while a DHCP server (the spectator) is answering.

Check, and fix if it prints `dhcp4: true`:

```bash
sudo netplan get ethernets | grep dhcp4
sudo cp /etc/netplan/50-cloud-init.yaml ~/50-cloud-init.yaml.bak
sudo sed -i 's/dhcp4: true/dhcp4: false/' /etc/netplan/50-cloud-init.yaml
sudo netplan generate && sudo nmcli con reload
```

The warning `Permissions for /etc/netplan/01-network-manager-all.yaml are too open` that these commands print is
unrelated and harmless.

### 3.4 Build the image

```bash
grep ^image_url scripts/prepare_raspbian_eyes_image.bash     # must end in ...bullseye-armhf-lite.img.xz
sudo bash scripts/prepare_raspbian_eyes_image.bash ~/.ssh/id_beholderpi
ls -lh *ansible-ready.img
```

- The operating system must be **Raspberry Pi OS Bullseye, 32-bit Lite**. Bookworm and later no longer ship
  `picamera`, and the install scripts refuse them.
- The script downloads the official image, checks its SHA1, and then modifies it: SSH is enabled, the user `pi` is
  created, the key pair is copied in, password login over SSH is disabled, and the discovery service is installed.
- The result is `2025-05-06-raspios-bullseye-armhf-lite-ansible-ready.img`, about 2 GB. Keep it; later reflashes use
  this file directly and do not need the script again.

## 4. Flashing an SD card

```bash
lsblk -o NAME,SIZE,MOUNTPOINT          # find the card by its size (about 30G), usually sdc
sudo umount /dev/sdc?* 2>/dev/null     # unmount its partitions if the desktop mounted them
sudo dd if=2025-05-06-raspios-bullseye-armhf-lite-ansible-ready.img of=/dev/sdc bs=4M status=progress conv=fsync
sync && sudo eject /dev/sdc
```

- **Check the device name with `lsblk` every time.** `dd` erases the target without asking. On the lab PC `sda` is a
  4.5T data disk and `nvme0n1` is the system disk.
- Writing takes 70 to 80 seconds. For most of that time nothing is printed, because the data is being flushed from
  memory to the card. To watch it, run `grep Dirty /proc/meminfo` in a second terminal; a falling number means it is
  writing.
- It worked when the last lines read `470+0 records out` and `1971322880 bytes (2.0 GB, 1.8 GiB) copied` with no error.
- Do not use Raspberry Pi Imager's customization settings with this image; they overwrite what the script prepared.

## 5. Installing an eye

Requirements: the PC's wired port is in `shared` mode and the spectator is powered off.

```bash
nmcli -g ipv4.method con show netplan-enp3s0     # must print: shared
```

### 5.1 Find the Pi

Put the card in the Pi, connect the network cable, power it on and wait two minutes. On its first boot the Pi expands
the file system and restarts once.

```bash
sudo sh -c 'cat /var/lib/NetworkManager/dnsmasq-*.leases'
```

Each line reads `expiry MAC IP hostname`. A freshly flashed Pi has the hostname `raspberrypi`.

- Pis that are already installed appear as `eyeNN`. Do not run an install script against them.
- The file keeps old entries until they expire. A reflashed Pi whose MAC was registered before gets the same address
  as before; only the hostname column changes back to `raspberrypi`. If the old name is still shown, the new system
  has not asked for an address yet. Wait a minute and look again.

Confirm that it is reachable and runs the right system:

```bash
pissh pi@<IP> 'hostname; grep VERSION_CODENAME /etc/os-release'      # raspberrypi / bullseye
```

`<IP>` is a placeholder here and below. Replace it, including the angle brackets, with the address from the lease file.

### 5.2 Run the install script

```bash
scripts/setup/install_eye.sh <IP> eye02
```

The name must be `eye01` to `eye99`; the Pi is then fixed at `10.0.0.1NN`. Do not reuse a number that another Pi holds.

What the script does:

1. Reads the OS version and the MAC address, and on Bullseye enables the legacy camera stack.
2. Records `MAC name` in `ansible/eyes-local.txt` and generates `ansible/vars_eyes-local.yml` from that list.
3. Reserves the fixed address for this MAC in the PC's shared network, sets the hostname, and reboots the Pi so that it
   moves to its fixed address before anything is installed.
4. Runs `ansible/install_eye.yml`: full system upgrade, packages (picamera, zmq, chrony and others), camera enabled,
   time synchronization, the BeholderPi code cloned to `/home/pi/src/BeholderPi`, and the streaming service enabled
   with automatic restart on failure.
5. Reboots the Pi and checks that the streaming service is running.

It takes 20 to 30 minutes. The task `Update all installed apt packages` alone takes 15 to 25 minutes and **prints
nothing while it runs**. To see that it is working:

```bash
pissh pi@<IP> 'pgrep -a "apt|dpkg" | head -3; uptime'
```

A listed `apt-get` or `dpkg` process means it is still upgrading.

The script ends with this line on success ("done: eye02 is streaming at 10.0.0.102:5555"):

```
完成: eye02 在 10.0.0.102:5555 推流
```

### 5.3 Check the eye

```bash
pissh pi@10.0.0.102 'systemctl is-active beholder_streaming; vcgencmd get_camera; journalctl -u beholder_streaming -b --no-pager | tail -4'
```

Expected: `active`, `supported=1 detected=1`, and a log that ends with `Starting recording`.
`detected=0` means the camera cable is not seated; power the Pi off and check both ends.

## 6. Installing the spectator

Do this after every eye is installed. Put a flashed card in the spectator Pi, power it on, find its address as in
section 5.1, then:

```bash
scripts/setup/install_spectator.sh <IP>
```

What the script does:

1. Checks the OS version.
2. Writes `ansible/vars_spectator-local.yml` with empty WiFi settings.
3. Installs chrony and dnsmasq and sets the hostname to `spectator`.
4. Runs `ansible/install_spectator.yml`: network configuration files, full system upgrade, packages, dnsmasq and
   systemd-networkd enabled, dhcpcd disabled.
5. Asks for confirmation, then changes the PC's wired port from `shared` to the fixed address `10.0.0.11/24`, reboots
   the spectator and waits until `10.0.0.1` answers a ping.

It takes 20 to 35 minutes.

The prompt `继续? [y/N]` ("continue?") switches the network. **Answer `y` only when the `PLAY RECAP` line above it shows
`failed=0`.** If a task failed, which is usually a package download cut off by a mirror, answer `N` and run the same
command again; finished steps are skipped.

The script ends with this line on success ("done: spectator is at 10.0.0.1; power-cycle each eye so that it fetches a
new address"):

```
完成: spectator 在 10.0.0.1。把各个 eye 断电重启一次，让它们重新拿地址。
```

Then power every eye off and on again.

## 7. Checking the whole system and starting beholder

```bash
# Is everything online? Adjust the addresses to the eyes you have.
for ip in 10.0.0.1 10.0.0.101 10.0.0.102; do ping -c1 -W2 $ip >/dev/null && echo "$ip up" || echo "$ip DOWN"; done

# Each eye: streaming service and clock
for ip in 10.0.0.101 10.0.0.102; do pissh pi@$ip 'hostname; systemctl is-active beholder_streaming; chronyc sources | grep 10.0.0.11; date'; done; date

# The streaming port can be checked without logging in
nc -zv -w2 10.0.0.102 5555
```

Expected:

- The streaming service is `active` on every eye.
- The `10.0.0.11` line starts with `^*`, meaning the eye is locked to the PC, and its Reach value is not 0. The
  measured offset on the day was 3 microseconds.
- Every `date` matches the PC's.
- `10.0.0.1` showing `^?` in `chronyc sources` is normal. The spectator does not serve time; the PC does.

Start the receiver in the `beholder` conda environment. For two cameras, `eye01` and `eye02`:

```bash
conda activate beholder
python beholder/main.py -c beholder/resources/config_beholder_2cam.yml
```

- The `sources` list in the configuration file holds the eye addresses (`10.0.0.101:5555`, `10.0.0.102:5555`). Edit it
  if your eyes have other numbers.
- Without `-c`, `beholder` uses `beholder/resources/config_beholder_local.yml` if it exists and otherwise the
  twelve-camera `config_beholder_default.yml`.
- Recordings go to `~/Videos/beholder` unless `-o <directory>` is given.

## 8. Adding or reinstalling an eye later

The camera network has no internet access in normal operation, so switch it back to the installation state first.

1. Power off the spectator. Otherwise two DHCP servers answer on the same network.
2. Put the wired port back into shared mode:
   ```bash
   nmcli con mod netplan-enp3s0 ipv4.method shared ipv4.addresses 10.0.0.11/24 && nmcli con up netplan-enp3s0
   nmcli -g ipv4.method con show netplan-enp3s0        # must print: shared
   ```
3. Flash and install as in sections 4 and 5.
4. Return the wired port to its fixed address:
   ```bash
   nmcli con mod netplan-enp3s0 ipv4.method manual ipv4.addresses 10.0.0.11/24 ipv4.gateway "" ipv4.never-default yes ipv6.method disabled && nmcli con up netplan-enp3s0
   ```
   Afterwards `nmcli -g ipv4.method con show netplan-enp3s0` must print `manual` and `ip -br addr show enp3s0` must
   show only `10.0.0.11/24`. If it prints `auto`, or `nmcli con up` fails with `IP configuration could not be reserved`,
   apply section 3.3.
5. Power the spectator on, power-cycle every eye, and check as in section 7.

Related cases:

- **Renaming an eye.** Run `scripts/setup/install_eye.sh <current IP> eyeNN` again; this needs internet access too.
  Remember that the name decides whether the picture is flipped.
- **Reinstalling the spectator.** Flash its card and run `install_spectator.sh` in shared mode, as in section 6.
- **Cloning a working card** (read it with `dd`, shrink it with PiShrink) gives a backup. A card flashed from such a
  clone has the same hostname and address as the original, so the two must not be online together.

## 9. Troubleshooting

Every entry below was hit during the installation on 2026-11-18.

| Symptom | Cause | What to do |
|---|---|---|
| `bash: IP: No such file or directory` | `<IP>` in a command is a placeholder and was pasted literally | Replace it with the real address |
| `cat: ...dnsmasq-*.leases: Permission denied` | Only root can read the directory, and the wildcard is expanded before `sudo` runs | `sudo sh -c 'cat ...'` |
| `umount: /dev/sdX?*: no mount point specified` | `sdX` is a placeholder | Use the real device, for example `/dev/sdc` |
| Nothing printed for a minute after `dd` starts | The data is being flushed from memory to the card | Wait. `grep Dirty /proc/meminfo` shows progress |
| ansible: `Timeout (12s) waiting for privilege escalation prompt` | The playbook rewrites `/etc/hosts` with the new name while the running hostname is still `raspberrypi`. `sudo` cannot resolve its own hostname and stalls | The scripts now set the hostname first. By hand: `pissh pi@<IP> "echo '127.0.1.1 eye02' \| sudo tee -a /etc/hosts; sudo hostnamectl set-hostname eye02"`, then run the script again |
| `No route to host` in the middle of the upgrade, ansible hangs | dhcpcd restarted during the upgrade and the Pi moved to its reserved fixed address | The eye script now moves the Pi first. By hand: Ctrl+C, then `pissh pi@<fixed IP> 'sudo dpkg --configure -a && sudo apt-get -y -f install'`, then run the script again with the fixed address |
| The final check prints `failed` repeatedly although `PLAY RECAP` shows `failed=0` | The camera settings only apply after a reboot, and a repeated playbook run does not trigger one | The eye script now always reboots before checking. By hand: `pissh pi@<IP> 'sudo reboot'` |
| Streaming service `failed` after boot, log shows `OSError: [Errno 101] Network is unreachable` | The service starts before DHCP has finished, the program fails to determine its own address and exits, and nothing restarts it | The playbook now installs a systemd drop-in with `Restart=on-failure`. For an eye installed earlier, use the command below this table |
| Spectator install: `Failed to fetch ... Remote end closed connection` | A package mirror dropped the connection | Answer `N` at the network prompt and run the script again |
| `nmcli con up` fails with `IP configuration could not be reserved`; `nmcli -g ipv4.method` prints `auto` after setting `manual`; the wired port has a second `10.0.0.x` address | `/etc/netplan/50-cloud-init.yaml` forces `dhcp4: true` on the wired interface, so the port waits for a DHCP server | Section 3.3. As a stopgap, power the spectator on and run `nmcli con up netplan-enp3s0` again |
| An eye is missing after a restart of the network, and its line in the spectator's lease file has an older expiry than the others | That eye has not requested an address since the spectator came back: it is off, did not boot, or its cable is loose | Check its power LED, ACT LED and network LEDs, then power-cycle it |
| `chronyc tracking` shows `Reference ID: 00000000` | The PC's chrony has no `allow` line and does not answer the Pis | Section 3.2 |
| `Permission denied (publickey)` | That Pi was installed with a different key | Find the original key, or reflash and reinstall |
| The lease file still shows the old hostname, for example `eye07` | That is the old entry; the new system has not requested an address yet | Wait a minute, or ask the Pi directly: `pissh pi@<IP> hostname` |
| `syntax error near unexpected token` mentioning the shell prompt | The terminal prompt was pasted along with the command | Harmless. Paste only the command |
| The Pi's fan keeps spinning | The PoE HAT fan follows the temperature or runs permanently; it says nothing about install progress | Look at the real load with `uptime` and `ps` |

Adding the automatic restart to an eye that was installed before the playbook had it:

```bash
pissh pi@<IP> 'sudo mkdir -p /etc/systemd/system/beholder_streaming.service.d && printf "[Unit]\nStartLimitIntervalSec=0\n\n[Service]\nRestart=on-failure\nRestartSec=5\n" | sudo tee /etc/systemd/system/beholder_streaming.service.d/restart.conf && sudo systemctl daemon-reload && sudo reboot'
```

## 10. Command reference

```bash
# Addresses handed out by the PC (shared mode)
sudo sh -c 'cat /var/lib/NetworkManager/dnsmasq-*.leases'

# Addresses handed out by the spectator (normal operation)
pissh pi@10.0.0.1 'cat /var/lib/misc/dnsmasq.leases'

# Mode of the wired port: shared = installing, manual = normal operation
nmcli -g ipv4.method,ipv4.addresses con show netplan-enp3s0

# Fixed addresses reserved on the PC, and the registered MAC addresses
cat /etc/NetworkManager/dnsmasq-shared.d/eyes.conf
cat ansible/eyes-local.txt

# Streaming log of one eye
pissh pi@10.0.0.102 'journalctl -u beholder_streaming -b --no-pager | tail -20'

# Which machines are synchronizing to the PC
sudo chronyc clients
```

If the wired connection is not called `netplan-enp3s0`, find its name with `nmcli con show` and prefix the install
scripts with `CON=<name>`. Both scripts also accept `KEY=<path>` for a different private key.

Login details set by the image script, for use with a monitor and keyboard: user `pi`, password `supersecret`; `pi` may
use `sudo` without a password. These are the upstream defaults and are public. To change them, edit
`user_password_clear` and `root_password_clear` in `scripts/prepare_raspbian_eyes_image.bash` and rebuild the image.

## 11. Repository layout and further documents

| Path | Contents |
|---|---|
| `scripts/prepare_raspbian_eyes_image.bash` | Builds the ansible-ready image (section 3.4) |
| `scripts/setup/install_eye.sh` | Installs one eye (section 5) |
| `scripts/setup/install_spectator.sh` | Installs the spectator and switches the PC's network (section 6) |
| `scripts/services/` | systemd units and scripts for discovery and streaming on the Pis |
| `scripts/launchers/` | Shell launchers for `beholder`, `stitch` and `tracer` |
| `ansible/` | Playbooks (`install_eye.yml`, `install_spectator.yml`, `install_beholder.yml`, `update.yml`, `reboot.yml`, `shutdown.yml`) and their templates |
| `piEye/` | The program that runs on each eye; configuration in `piEye/resources/` |
| `beholder/` | The receiver and recorder that runs on the PC; configurations in `beholder/resources/` |
| `tools/` | Post-processing: stitching, tracing, tracking, and a dummy stream server for testing |
| `arduino/`, `physical/` | Sync-light firmware (`syncblink`) and PCB design files |

Further documents:

- [docs/Installation_Walkthrough_zh.md](docs/Installation_Walkthrough_zh.md): this installation guide in Chinese
- [docs/Installation_Beholder.md](docs/Installation_Beholder.md): setting up the recording PC, including FFmpeg with NVENC
- [docs/ffmpeg_with_nvenc.md](docs/ffmpeg_with_nvenc.md): notes on building FFmpeg for NVIDIA encoding
- [docs/Synchronization.md](docs/Synchronization.md): how frames are timestamped and synchronized
- [docs/Networking.md](docs/Networking.md), [docs/Installation_Eye.md](docs/Installation_Eye.md),
  [docs/Installation_Spectator.md](docs/Installation_Spectator.md): the original upstream notes that the install scripts
  automate
- [docs/Installation_PXE_Boot.md](docs/Installation_PXE_Boot.md): booting eyes from the network instead of SD cards
- [docs/Telemetry.md](docs/Telemetry.md): optional telemetry with telegraf
- [docs/todo.md](docs/todo.md): open tasks

## 12. Credits

BeholderPi was written by Ronny Eichler ([upstream repository](https://github.com/wonkoderverstaendige/BeholderPi)).
The system was inspired by [Saxena et al. 2018](https://www.physiology.org/doi/full/10.1152/jn.00215.2018)
([code](https://github.com/DeshmukhLab/PicameraPaper)).
