#!/bin/sh
# Chạy MỘT lần trên VM Ubuntu 24.04 mới: cài Docker, tạo thư mục app, mở cổng 80/443 ở firewall của OS.
#   ssh -i <key> azureuser@<host> 'sh -s' < deploy/vm/bootstrap.sh
# Firewall của nhà cung cấp (Azure: Network Security Group) vẫn phải mở 80/443 riêng.
set -eu

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"

if sudo ufw status 2>/dev/null | grep -q "Status: active"; then
  sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
fi
# Một số image (Oracle) có rule REJECT trong iptables INPUT: chèn ACCEPT trước nó.
if sudo iptables -S INPUT 2>/dev/null | grep -q -- "-j REJECT"; then
  for port in 80 443; do
    sudo iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
      || sudo iptables -I INPUT 1 -p tcp --dport "$port" -j ACCEPT
  done
  sudo netfilter-persistent save >/dev/null 2>&1 || true
fi

mkdir -p "$HOME/heritage/data"
echo "bootstrap xong: $(sudo docker --version)"
