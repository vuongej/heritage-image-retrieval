#!/bin/sh
# Chạy MỘT lần trên VM Oracle mới (Ubuntu 24.04): cài Docker, mở cổng 80/443, tạo thư mục app.
#   ssh -i <key> ubuntu@<ip> 'sh -s' < deploy/oracle/bootstrap.sh
set -eu

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"

# Image Ubuntu của Oracle chặn mọi cổng trừ 22 bằng iptables, ngoài Security List của VCN.
for port in 80 443; do
  sudo iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null \
    || sudo iptables -I INPUT 5 -p tcp --dport "$port" -m state --state NEW -j ACCEPT
done
sudo netfilter-persistent save >/dev/null 2>&1 || sudo sh -c 'iptables-save > /etc/iptables/rules.v4'

mkdir -p "$HOME/heritage/data"
echo "bootstrap xong: $(docker --version 2>/dev/null || sudo docker --version)"
