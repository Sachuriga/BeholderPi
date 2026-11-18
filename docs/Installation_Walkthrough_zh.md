# BeholderPi 安装全流程（eye + spectator）

2026-11-18 在实验室电脑上实际走通后整理。所有命令都在 Linux 电脑（beholder 机）上、仓库根目录 `~/BeholderPi` 里执行。

验证情况：

- 第 1–5 节的流程当天已在真机上跑通（eye02、spectator）。
- `scripts/setup/` 下两个脚本和 `ansible/install_eye.yml` 在跑通之后又做了修复（见第 7 节），修复后的版本只做过语法检查，还没有完整重跑。如果脚本行为和本文不符，按第 7 节的手动办法处理。
- 第 6 节"切回共享模式"的命令写成文档时尚未实际执行过。

## 0. 概览

| 角色 | 主机名 | 地址 | 作用 |
|---|---|---|---|
| 电脑 | beholder | 10.0.0.11 | 接收画面、录像；**时间源**（chrony） |
| 一台 Pi | spectator | 10.0.0.1 | 相机网络的 DHCP，按主机名分配地址 |
| 相机 Pi | eyeNN | 10.0.0.1NN | 采集并在 5555 端口推流（eye02 → 10.0.0.102） |

要点：

- **所有卡刷同一个镜像**。Pi 是 eye 还是 spectator，取决于开机后跑哪个安装脚本。
- **先装完所有 eye，最后装 spectator**。spectator 接管后相机网络没有外网，eye 无法再下载软件包。
- 安装期间电脑有线口是"共享"模式（给 Pi 发地址并提供外网）；装完后切到固定 `10.0.0.11`。
- 主机名决定画面方向：默认配置对 `eye07`–`eye12` 做上下左右翻转，`eye01`–`eye06` 不翻（`piEye/resources/config_pieye_default.yml`）。
- eye 上的代码是从上游 `wonkoderverstaendige/BeholderPi` 克隆的，不是自己的 fork。在 fork 里改 `piEye/` 不会自动到 Pi 上。

为了少打字，先定义一个别名（每开一个新终端要重新定义）：

```bash
alias pissh='ssh -i ~/.ssh/id_beholderpi -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR'
```

## 1. 一次性准备（电脑）

### 1.1 密钥

```bash
ls ~/.ssh/id_beholderpi || ssh-keygen -t ed25519 -f ~/.ssh/id_beholderpi -C "BeholderPi keys"
```

passphrase 留空。**这把密钥要保管好**：镜像里只放了它的公钥，换了密钥就登录不了已装好的 Pi（会报 `Permission denied (publickey)`），只能重刷。

### 1.2 电脑给相机网络授时

eye 和 spectator 都向 `10.0.0.11` 对时。chrony 默认不回答别的机器，必须显式允许：

```bash
printf 'allow 10.0.0.0/24\nlocal stratum 10\n' | sudo tee /etc/chrony/conf.d/beholder.conf
sudo systemctl restart chrony
```

这个文件不在任何脚本里，重装电脑系统后要重新加。

### 1.3 生成镜像

```bash
grep ^image_url scripts/prepare_raspbian_eyes_image.bash     # 必须是 ...bullseye-armhf-lite.img.xz
sudo bash scripts/prepare_raspbian_eyes_image.bash ~/.ssh/id_beholderpi
ls -lh *ansible-ready.img
```

- 系统必须是 **Bullseye**（32 位 Lite）。Bookworm 及以后没有 picamera，装不了相机。
- 脚本下载官方镜像、校验 SHA1，然后打开 SSH、放入密钥、装上 discovery 服务。
- 产物：`2025-05-06-raspios-bullseye-armhf-lite-ansible-ready.img`（约 2 GB）。以后重刷直接用这个文件，不用重新生成。

## 2. 刷卡

```bash
lsblk -o NAME,SIZE,MOUNTPOINT          # 找到约 30G 的卡，通常是 sdc
sudo umount /dev/sdc?* 2>/dev/null
sudo dd if=2025-05-06-raspios-bullseye-armhf-lite-ansible-ready.img of=/dev/sdc bs=4M status=progress conv=fsync
sync && sudo eject /dev/sdc
```

- **每次都先 `lsblk` 确认设备名**。这台电脑上 `sda` 是 4.5T 数据盘，`nvme0n1` 是系统盘，写错就全没了。
- 写入约 70–80 秒，其中大半时间没有任何输出（数据在从内存落盘），不是卡死。想看进度：另开终端 `grep Dirty /proc/meminfo`，数字在下降就是在写。
- 结尾出现 `1971322880 bytes ... copied` 且无报错即成功。

## 3. 安装 eye

前提：电脑有线口是共享模式，spectator 没有通电。

### 3.1 找到 Pi

卡插进 Pi，接网线，上电，等两分钟（首次开机会自动扩容并重启一次）。

```bash
sudo sh -c 'cat /var/lib/NetworkManager/dnsmasq-*.leases'
```

每行是 `时间 MAC IP 主机名`。新刷的卡主机名是 `raspberrypi`。注意区分已经装好的 Pi（主机名是 `eyeNN`），不要对它们运行安装脚本。

确认连得上、系统正确：

```bash
pissh pi@<IP> 'hostname; grep VERSION_CODENAME /etc/os-release'      # raspberrypi / bullseye
```

### 3.2 运行安装脚本

```bash
scripts/setup/install_eye.sh <IP> eye02
```

名字必须是 `eye01`–`eye99`，对应固定地址 `10.0.0.1NN`。不要用已被别的 Pi 占用的编号。

脚本做的事：

1. 检查系统版本，读 MAC，Bullseye 上打开 legacy camera。
2. 把 `MAC 名字` 记入 `ansible/eyes-local.txt`，生成 `ansible/vars_eyes-local.yml`。
3. 在电脑的共享网络里给这个 MAC 预留固定地址，改主机名，重启 Pi 让它换到固定地址。
4. 跑 `ansible/install_eye.yml`：系统升级、装 picamera/zmq/chrony、打开摄像头、对时配置、克隆代码、启用推流服务。
5. 重启 Pi，验证推流服务。

耗时 20–30 分钟，其中 `Update all installed apt packages` 占 15–25 分钟且**没有任何输出**。想确认它在跑：

```bash
pissh pi@<IP> 'pgrep -a "apt|dpkg" | head -3; uptime'
```

成功标志：

```
完成: eye02 在 10.0.0.102:5555 推流
```

### 3.3 单台检查

```bash
pissh pi@10.0.0.102 'systemctl is-active beholder_streaming; vcgencmd get_camera; journalctl -u beholder_streaming -b --no-pager | tail -4'
```

应为 `active`、`supported=1 detected=1`，日志以 `Starting recording` 结尾。`detected=0` 是排线问题，断电检查排线两端。

## 4. 安装 spectator（最后做）

另一张卡插进 spectator 的 Pi，上电，按 3.1 找到它的 IP，然后：

```bash
scripts/setup/install_spectator.sh <IP>
```

脚本做的事：

1. 检查系统版本。
2. 写 `ansible/vars_spectator-local.yml`（WiFi 留空）。
3. 预装 chrony 和 dnsmasq，改主机名为 `spectator`。
4. 跑 `ansible/install_spectator.yml`：写网络配置、系统升级、装包、启用 dnsmasq 和 systemd-networkd、停用 dhcpcd。
5. 询问后把电脑有线口从共享模式改成固定 `10.0.0.11/24`，重启 spectator，等 `10.0.0.1` 能 ping 通。

耗时 20–35 分钟。**只有 `PLAY RECAP` 里 `failed=0` 时才对 `继续? [y/N]` 回答 `y`**；如果有任务失败（多半是下载软件包时镜像站断线），回答 `N`，重跑同一条命令即可，已完成的步骤会跳过。

成功标志：

```
完成: spectator 在 10.0.0.1。把各个 eye 断电重启一次，让它们重新拿地址。
```

然后把所有 eye 断电再上电。

## 5. 整体验证

```bash
# 都在线吗（按实际的 eye 编号改地址）
for ip in 10.0.0.1 10.0.0.101 10.0.0.102; do ping -c1 -W2 $ip >/dev/null && echo "$ip 在线" || echo "$ip 不通"; done

# 每台 eye：推流 + 对时
for ip in 10.0.0.101 10.0.0.102; do pissh pi@$ip 'hostname; systemctl is-active beholder_streaming; chronyc sources | grep 10.0.0.11; date'; done; date

# 不登录也能看推流端口
nc -zv -w2 10.0.0.102 5555
```

预期：

- 推流服务 `active`。
- `10.0.0.11` 那行以 `^*` 开头（已锁定），Reach 不为 0。实测偏差在微秒级。
- 各台 `date` 与电脑一致。
- `chronyc sources` 里 `10.0.0.1` 显示 `^?` 是正常的，spectator 不对外授时。

## 6. 以后追加或重装一台 eye

相机网络平时没有外网，要临时切回安装状态：

1. spectator 断电（避免两个 DHCP 服务器）。
2. 有线口改回共享模式：
   ```bash
   nmcli con mod netplan-enp3s0 ipv4.method shared ipv4.addresses 10.0.0.11/24 && nmcli con up netplan-enp3s0
   nmcli -g ipv4.method con show netplan-enp3s0        # 应输出 shared
   ```
3. 按第 2、3 节刷卡、安装。
4. 切回固定地址：
   ```bash
   nmcli con mod netplan-enp3s0 ipv4.method manual ipv4.addresses 10.0.0.11/24 ipv4.gateway "" ipv4.never-default yes ipv6.method disabled && nmcli con up netplan-enp3s0
   ```
5. spectator 上电，所有 eye 断电重启，按第 5 节验证。

其他情况：

- **只是换名字**：重跑 `scripts/setup/install_eye.sh <当前IP> eyeNN`（同样需要外网）。
- **重装 spectator**：刷卡后在共享模式下跑 `install_spectator.sh`，和第 4 节一样。
- **克隆一张现成的卡**（`dd` 读出再用 PiShrink 压缩）可以当备份，但刷出来的卡和原机主机名、地址完全相同，两台同时在线会冲突。

## 7. 踩过的坑

| 现象 | 原因 | 处理 |
|---|---|---|
| `bash: IP: No such file or directory` | 命令里的 `<IP>` 是占位符，没替换 | 换成实际地址 |
| `cat: ...dnsmasq-*.leases: Permission denied` | 目录只有 root 能读，通配符在 sudo 之前展开 | `sudo sh -c 'cat ...'` |
| `dd` 之后长时间没输出 | 数据在从内存落盘 | 等；`grep Dirty /proc/meminfo` 看进度 |
| ansible：`Timeout (12s) waiting for privilege escalation prompt` | playbook 先改了 `/etc/hosts`，运行中的主机名还是 `raspberrypi`，sudo 解析不到自己而卡住 | 脚本已改为先改主机名。手动：`pissh pi@<IP> "echo '127.0.1.1 eye02' \| sudo tee -a /etc/hosts; sudo hostnamectl set-hostname eye02"` 后重跑 |
| 升级跑到一半 `No route to host`，ansible 挂住 | 升级中 dhcpcd 重启，Pi 换到了预留的固定地址 | 脚本已改为先换地址再装。手动：Ctrl+C，`pissh pi@<固定IP> 'sudo dpkg --configure -a && sudo apt-get -y -f install'`，再用固定 IP 重跑 |
| 装完验证一串 `failed`，但 `PLAY RECAP` 是 `failed=0` | 摄像头设置要重启才生效，而 playbook 重跑时不会触发重启 | 脚本已改为总是重启后验证。手动：`pissh pi@<IP> 'sudo reboot'` |
| 开机后推流服务 `failed`，日志 `OSError: [Errno 101] Network is unreachable` | 服务在 DHCP 完成前启动，查本机 IP 失败后退出，且没有自动重试 | playbook 已加 systemd 补丁（`Restart=on-failure`）。手动补丁见下 |
| spectator 安装中 `Failed to fetch ... Remote end closed connection` | 镜像站临时断线 | 对切换网络回答 `N`，重跑脚本 |
| `chronyc tracking` 显示 `Reference ID: 00000000` | 电脑的 chrony 没有 `allow`，不给别人授时 | 第 1.2 节 |
| `Permission denied (publickey)` | 那台 Pi 是用另一把密钥装的 | 找到原密钥，或重刷重装 |
| 风扇一直转 | PoE HAT 风扇按温度控制或常转，与安装进度无关 | 用 `uptime`、`ps` 看实际负载 |

给已装好的 eye 手动加推流自动重试补丁：

```bash
pissh pi@<IP> 'sudo mkdir -p /etc/systemd/system/beholder_streaming.service.d && printf "[Unit]\nStartLimitIntervalSec=0\n\n[Service]\nRestart=on-failure\nRestartSec=5\n" | sudo tee /etc/systemd/system/beholder_streaming.service.d/restart.conf && sudo systemctl daemon-reload && sudo reboot'
```

## 8. 常用命令

```bash
# 共享模式下，电脑发出去的地址
sudo sh -c 'cat /var/lib/NetworkManager/dnsmasq-*.leases'

# spectator 接管后，它发出去的地址
pissh pi@10.0.0.1 'cat /var/lib/misc/dnsmasq.leases'

# 有线口当前模式（shared = 安装状态，manual = 运行状态）
nmcli -g ipv4.method,ipv4.addresses con show netplan-enp3s0

# 电脑上预留的固定地址，以及登记过的 MAC
cat /etc/NetworkManager/dnsmasq-shared.d/eyes.conf
cat ansible/eyes-local.txt

# 某台 eye 的推流日志
pissh pi@10.0.0.102 'journalctl -u beholder_streaming -b --no-pager | tail -20'

# 哪些机器在向电脑对时
sudo chronyc clients
```

有线口的连接名不是 `netplan-enp3s0` 时，用 `nmcli con show` 查，并在安装脚本前加 `CON=<连接名>`。
