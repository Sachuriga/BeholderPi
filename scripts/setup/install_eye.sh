#!/usr/bin/env bash
# 用法: scripts/setup/install_eye.sh <Pi 当前的 IP> <名字, 如 eye01>
set -euo pipefail
IP="${1:?用法: scripts/setup/install_eye.sh <Pi的IP> <eye01|eye02|...>}"
NAME="${2:?用法: scripts/setup/install_eye.sh <Pi的IP> <eye01|eye02|...>}"
REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
KEY="${KEY:-$HOME/.ssh/id_beholderpi}"
CON="${CON:-netplan-enp3s0}"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=10)

[[ "$NAME" =~ ^eye([0-9]{2})$ ]] || { echo "名字必须是 eye01 ~ eye99 这种格式"; exit 1; }
FIXED_IP="10.0.0.1${BASH_REMATCH[1]}"
[[ -f "$KEY" ]] || { echo "找不到私钥 $KEY"; exit 1; }
cd "$REPO"

echo "== 1/5 检查 Pi =="
OS=$("${SSH[@]}" "pi@$IP" '. /etc/os-release; echo $VERSION_CODENAME')
MAC=$("${SSH[@]}" "pi@$IP" 'cat /sys/class/net/eth0/address')
echo "系统: $OS   MAC: $MAC"
case "$OS" in
  buster) ;;
  bullseye) echo "Bullseye: 打开 legacy camera"; "${SSH[@]}" "pi@$IP" 'sudo raspi-config nonint do_legacy 0' ;;
  *) echo "这个镜像是 $OS，没有 picamera，装不了。请改刷 Buster 或 Bullseye (legacy) 的镜像。"; exit 1 ;;
esac

echo "== 2/5 登记 MAC =="
LIST=ansible/eyes-local.txt
touch "$LIST"
grep -v -e "^$MAC " -e " $NAME\$" "$LIST" > "$LIST.tmp" || true
echo "$MAC $NAME" >> "$LIST.tmp"
mv "$LIST.tmp" "$LIST"
{
  echo "---"
  echo "mac_address_mapping:"
  while read -r m n; do printf '  "%s":\n    name: %s\n' "$m" "$n"; done < "$LIST"
  printf 'dns_nameservers:\n  - "10.0.0.1"\n  - "8.8.4.4"\nbeholder_router:\n  - "10.0.0.1"\n'
} > ansible/vars_eyes-local.yml

echo "== 3/5 固定 IP: $NAME -> $FIXED_IP =="
if [[ "$(nmcli -g ipv4.method con show "$CON")" == "shared" ]]; then
  F=/etc/NetworkManager/dnsmasq-shared.d/eyes.conf
  sudo mkdir -p "$(dirname "$F")"; sudo touch "$F"
  sudo sed -i "/^dhcp-host=$MAC,/d;/,$FIXED_IP\$/d" "$F"
  echo "dhcp-host=$MAC,$FIXED_IP" | sudo tee -a "$F" > /dev/null
  nmcli con up "$CON" > /dev/null
  sleep 5
else
  echo "有线口不是共享模式，跳过 (由 spectator 按主机名分配)"
fi
# 先改主机名并重启，让 Pi 现在就换到固定地址。
# 否则: (1) playbook 改写 /etc/hosts 后旧主机名解析不到，sudo 卡住，ansible 超时;
#       (2) apt 升级中途 dhcpcd 重启，Pi 换地址，ansible 连接断开。
"${SSH[@]}" "pi@$IP" "grep -q ' $NAME\$' /etc/hosts || echo '127.0.1.1 $NAME' | sudo tee -a /etc/hosts > /dev/null; sudo hostnamectl set-hostname $NAME"
if [[ "$IP" != "$FIXED_IP" ]]; then
  "${SSH[@]}" "pi@$IP" 'sudo reboot' 2>/dev/null || true
  echo "等 Pi 重启并换到 $FIXED_IP ..."
  sleep 15
  for i in $(seq 1 30); do
    if "${SSH[@]}" "pi@$FIXED_IP" true 2>/dev/null; then IP="$FIXED_IP"; break; fi
    sleep 5
  done
  [[ "$IP" == "$FIXED_IP" ]] || echo "没有换到 $FIXED_IP，继续用 $IP"
fi

echo "== 4/5 运行 ansible =="
INV=$(mktemp)
printf '[new_eyes]\n%s\n\n[new_eyes:vars]\nansible_ssh_user=pi\n' "$IP" > "$INV"
ANSIBLE_HOST_KEY_CHECKING=False ansible-playbook ansible/install_eye.yml \
  --private-key "$KEY" --inventory "$INV" \
  --extra-vars "@ansible/vars_eyes-local.yml" --limit new_eyes || echo "(Pi 重启换 IP 时最后一步可能报连接错误，继续验证)"
rm -f "$INV"

echo "== 5/5 重启 Pi 并验证 =="
# 摄像头设置 (start_x / legacy camera) 重启后才生效，playbook 不一定会触发重启。
"${SSH[@]}" "pi@$IP" 'sudo reboot' 2>/dev/null || true
sleep 20
for i in $(seq 1 30); do
  if ping -c1 -W2 "$FIXED_IP" > /dev/null 2>&1; then
    sleep 10
    "${SSH[@]}" "pi@$FIXED_IP" 'hostname; systemctl is-active beholder_streaming' && \
      echo "完成: $NAME 在 $FIXED_IP:5555 推流" && exit 0
  fi
  sleep 5
done
echo "$FIXED_IP 没有响应。用 discovery 脚本看看它现在的 IP。"; exit 1
