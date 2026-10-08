# jtop

Hardware components and live usage in your terminal, htop style.
Three tabs: **Components** (CPU, memory, motherboard, GPU, battery, disks, network), **Usage**
(per-core CPU, RAM/swap, disk and network throughput, filesystems, temperatures, battery)
and **Processes** (sorted by CPU, with memory, user and command).

Linux only, Python 3 standard library, no dependencies.

![Components tab](screenshots/components.png)

![Usage tab](screenshots/usage.png)

![Processes tab](screenshots/processes.png)

## Install (Debian / Ubuntu)

```sh
sudo curl -fsSLo /usr/share/keyrings/jtop.gpg https://notdjz.github.io/jtop/jtop.gpg
echo "deb [signed-by=/usr/share/keyrings/jtop.gpg] https://notdjz.github.io/jtop ./" | sudo tee /etc/apt/sources.list.d/jtop.list
sudo apt update
sudo apt install jtop
```

Then run `jtop`. Updates come with `sudo apt upgrade`.

For fun: `jtop --fun`
