#!/usr/bin/env bash
# 用法: scripts/setup/install_spectator.sh <Pi 当前的 IP>     (先把所有 eye 装完再跑这个!)
set -euo pipefail
IP="${1:?用法: scripts/setup/install_spectator.sh <Pi的IP>}"
REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
KEY="${KEY:-$HOME/.ssh/id_beholderpi}"
CON="${CON:-netplan-enp3s0}"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=10)
[[ -f "$KEY" ]] || { echo "找不到私钥 $KEY"; exit 1; }
cd "$REPO"

echo "== 1/5 检查 Pi =="
OS=$("${SSH[@]}" "pi@$IP" '. /etc/os-release; echo $VERSION_CODENAME')
echo "系统: $OS"
case "$OS" in buster|bullseye) ;; *) echo "镜像是 $OS，playbook 依赖 dhcpcd，只支持 Buster/Bullseye。"; exit 1 ;; esac

echo "== 2/5 写配置 =="
printf 'WIFI_SSID: ""\nWIFI_PSK: ""\nWIFI_COUNTRY: "NL"\n' > ansible/vars_spectator-local.yml

echo "== 3/5 预装 chrony 和 dnsmasq =="
"${SSH[@]}" "pi@$IP" 'sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq chrony dnsmasq'

echo "== 4/5 运行 ansible =="
INV=$(mktemp)
printf '[spectator]\n%s\n\n[spectator:vars]\nansible_ssh_user=pi\n' "$IP" > "$INV"
ANSIBLE_HOST_KEY_CHECKING=False timeout 1800 ansible-playbook ansible/install_spectator.yml \
  --private-key "$KEY" --inventory "$INV" \
  --extra-vars "@ansible/vars_spectator-local.yml" || echo "(最后一步 spectator 换 IP，连接断开是正常的，继续验证)"
rm -f "$INV"

echo "== 5/5 电脑有线口: 共享模式 -> 固定 10.0.0.11 =="
echo "切换后相机网络里的 Pi 不能再上外网。"
read -r -p "继续? [y/N] " ok
[[ "$ok" == "y" || "$ok" == "Y" ]] || { echo "已停在这里，电脑仍是共享模式。"; exit 0; }
nmcli con mod "$CON" ipv4.method manual ipv4.addresses 10.0.0.11/24 ipv4.gateway "" ipv4.never-default yes ipv6.method disabled
nmcli con up "$CON" > /dev/null
sleep 3
"${SSH[@]}" "pi@$IP" 'sudo reboot' 2>/dev/null || "${SSH[@]}" pi@10.0.0.1 'sudo reboot' 2>/dev/null || true
echo "等 spectator 重启..."
for i in $(seq 1 30); do
  sleep 5
  if ping -c1 -W2 10.0.0.1 > /dev/null 2>&1; then
    echo "完成: spectator 在 10.0.0.1。把各个 eye 断电重启一次，让它们重新拿地址。"; exit 0
  fi
done
echo "10.0.0.1 没有响应。把 spectator 断电重启一次再 ping 10.0.0.1。"; exit 1
