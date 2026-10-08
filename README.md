# jtop

Hardware components and live usage in your terminal, htop style.
Two tabs: **Components** (CPU, memory, motherboard, GPU, disks, network) and **Usage**
(per-core CPU, RAM/swap, disk and network throughput, filesystems, temperatures).

Linux only, Python 3 standard library, no dependencies.

## Install (Debian / Ubuntu)

```sh
sudo curl -fsSLo /usr/share/keyrings/jtop.gpg https://notdjz.github.io/jtop/jtop.gpg
echo "deb [signed-by=/usr/share/keyrings/jtop.gpg] https://notdjz.github.io/jtop ./" | sudo tee /etc/apt/sources.list.d/jtop.list
sudo apt update
sudo apt install jtop
```

Then run `jtop`. Updates come with `sudo apt upgrade`.

## Keys

`Tab` switch · `↑` `↓` scroll · `q` quit
