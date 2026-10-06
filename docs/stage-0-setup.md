# Stage 0 setup: Ubuntu on the GPU PC (WSL)

Kit's server runs in Ubuntu under WSL (Windows Subsystem for Linux) on the PC with
the RTX 2070 Super. That makes it a real Linux server from day one: when the PC
later becomes a dedicated Linux box, the same commands, paths and services carry
over, and Kit's data folder is copied across.

Windows keeps two jobs: the NVIDIA driver, and keeping Ubuntu running. Everything
else in this guide happens in the Ubuntu terminal.

Work through the steps, then run `kit check`. Stage 0 is done when every
checklist box at the bottom is ticked.

## 1. Windows side: driver, WSL and keeping Ubuntu awake

**NVIDIA driver.** Install the latest Game Ready or Studio driver for Windows from
nvidia.com. Do not install an NVIDIA driver inside Ubuntu: WSL passes the
Windows driver through.

**Update WSL** in a Windows terminal (PowerShell):

```
wsl --update
wsl --list --verbose
```

Ubuntu should show `VERSION 2`. If it says 1: `wsl --set-version Ubuntu 2`.

**Turn on systemd** so Ollama, Tailscale and later Kit run as services, the way
they will on the real server. In Ubuntu:

```
cat /etc/wsl.conf
```

If it doesn't contain `systemd=true` under `[boot]`, add it:

```
sudo tee -a /etc/wsl.conf <<'CONF'
[boot]
systemd=true
CONF
```

Then in PowerShell, `wsl --shutdown`, and open Ubuntu again.

**Keep Ubuntu running.** WSL stops Ubuntu a little while after the last window
closes, which would stop Kit. A Windows scheduled task keeps it up:

1. Open **Task Scheduler**, **Create Task**. Name: `Kit WSL`.
2. General: **Run only when user is logged on**, and tick **Hidden**.
3. Triggers: **At log on** of your user.
4. Actions: Program `wsl.exe`, arguments `-d Ubuntu --exec sleep infinity`.
5. Settings: untick **Stop the task if it runs longer than**.

Set Windows to sign you in automatically after a restart (or just stay signed
in), so Kit comes back on its own after updates. Use the name from
`wsl --list` if your distro isn't called exactly `Ubuntu`.

## 2. GPU check

In Ubuntu:

```
nvidia-smi
```

It should list the RTX 2070 SUPER with 8192 MiB. If the command isn't found, the
Windows driver is too old: update it and run `wsl --shutdown`.

## 3. Python and the basics

```
sudo apt update && sudo apt install -y git curl cifs-utils
python3 --version
```

- **Ubuntu 24.04** comes with Python 3.12: `sudo apt install -y python3.12-venv`.
- **Ubuntu 22.04** has 3.10, which is too old. Add 3.12:

  ```
  sudo add-apt-repository -y ppa:deadsnakes/ppa
  sudo apt install -y python3.12 python3.12-venv
  ```

## 4. Ollama and the local model

If Ollama for Windows is installed, quit it from the tray and uninstall it, so
two copies don't fight over port 11434 and the GPU memory. Then in Ubuntu:

```
curl -fsSL https://ollama.com/install.sh | sh
```

The installer sets Ollama up as a service. Give it the settings that keep Kit's
models on the 8 GB card:

```
sudo systemctl edit ollama
```

and add, between the comment lines it shows:

```
[Service]
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=3"
```

Then restart it and pull Kit's everyday model (about 5 GB):

```
sudo systemctl restart ollama
ollama pull qwen3:8b
ollama run qwen3:8b "Say hello in five words"
ollama ps
```

`ollama ps` should show the model at `100% GPU`.

## 5. Tailscale (inside Ubuntu)

Tailscale runs inside Ubuntu, so Ubuntu itself is `kit-server` on your tailnet,
exactly as the Linux server will be later. Your phone and desk PC reach Kit
there without any Windows port forwarding.

```
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --hostname=kit-server
```

Open the link it prints and sign in with the same account as your desk PC and
phone. In the Tailscale admin console make sure MagicDNS is on. If this
Windows PC already runs Tailscale under the name `kit-server`, rename the
Windows one (for example `gpu-pc`) so the name belongs to Ubuntu.

Check from the desk PC: `tailscale ping kit-server`. Check from the phone with
Wi-Fi off: the Tailscale app shows `kit-server` as connected.

## 6. Synology: a `kit` user and the mounts

Kit gets its own NAS account, so the NAS itself enforces what Kit may touch.

1. DSM, Control Panel, User & Group: create a user `kit` with a strong password.
2. Control Panel, Shared Folder, then for each share Kit should read (photos,
   documents): Edit, Permissions, give `kit` **Read only**.
3. For the Obsidian vault folder: File Station, right-click the vault folder,
   Properties, Permission, Create: `kit`, **Read & Write**. Everything else
   stays read-only.
4. Give the NAS a fixed IP address (a DHCP reservation on your router), for
   example 192.168.1.50.

In Ubuntu, store the `kit` user's NAS password where only root can read it:

```
sudo tee /etc/kit-nas.cred > /dev/null <<'CRED'
username=kit
password=THE-KIT-PASSWORD
CRED
sudo chmod 600 /etc/kit-nas.cred
```

Make a mount point per share and add them to `/etc/fstab`. Adjust the share
paths to yours; `id -u` and `id -g` show your numbers if they aren't 1000:

```
sudo mkdir -p /mnt/nas/photo /mnt/nas/documents /mnt/nas/vault
sudo tee -a /etc/fstab <<'FSTAB'
//192.168.1.50/photo              /mnt/nas/photo     cifs credentials=/etc/kit-nas.cred,uid=1000,gid=1000,iocharset=utf8,_netdev,nofail,x-systemd.automount 0 0
//192.168.1.50/home/Documents     /mnt/nas/documents cifs credentials=/etc/kit-nas.cred,uid=1000,gid=1000,iocharset=utf8,_netdev,nofail,x-systemd.automount 0 0
//192.168.1.50/home/Obsidian      /mnt/nas/vault     cifs credentials=/etc/kit-nas.cred,uid=1000,gid=1000,iocharset=utf8,_netdev,nofail,x-systemd.automount 0 0
FSTAB
sudo systemctl daemon-reload
sudo mount -a
ls /mnt/nas/photo | head
```

The mounts are not marked read-only on purpose: the NAS's own permissions for
`kit` do the protecting, and `kit check` proves it by trying a write.

## 7. Anthropic API key

1. At platform.claude.com, create an API key for Kit. A Claude subscription
   doesn't include API use, so this is billed separately, per use.
2. Under Limits, set a monthly spend limit you're comfortable with.
3. Save it after step 8 has created Kit's data folder:

```
nano /var/lib/kit/secrets/anthropic_api_key     # paste the key, save
chmod 700 /var/lib/kit/secrets
chmod 600 /var/lib/kit/secrets/anthropic_api_key
```

## 8. Install Kit and run the checks

Keep the code in Ubuntu's own home folder, not under `/mnt/c`, which is much
slower from Linux.

```
cd ~
git clone https://github.com/Senitage/Kit kit
cd kit
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
sudo mkdir -p /var/lib/kit && sudo chown "$USER": /var/lib/kit
kit init
```

`kit init` fills `/var/lib/kit` and writes a starter
`/var/lib/kit/config/settings.toml`. Open it (`nano` is fine) and fill in the
`[nas]` section with the mount points from step 6:

```toml
[nas]
vault = '/mnt/nas/vault'

[nas.read_only_shares]
photos = '/mnt/nas/photo'
documents = '/mnt/nas/documents'
```

Then:

```
kit check
```

Every line should say PASS. The NAS check writes a tiny `.kit-write-test` file
and deletes it straight away, to prove the read-only shares really refuse writes
and the vault accepts them. The Claude check only looks up the model, so it
costs nothing.

## When the PC becomes a Linux server

Install Ubuntu on the PC with its NVIDIA driver (`sudo ubuntu-drivers install`),
then repeat steps 2 to 8. Copy `/var/lib/kit` across before running `kit init`
(it holds settings, secrets and memory), along with `/etc/kit-nas.cred` and the
`fstab` lines. Step 1 and the Windows scheduled task are no longer needed.

## Stage 0 test checklist

- [ ] `nvidia-smi` in Ubuntu shows the 2070 Super (`kit check`: gpu)
- [ ] Ollama answers, on the GPU, with tokens/s shown (`kit check`: ollama)
- [ ] The desk PC and phone reach `kit-server` over Tailscale, including from mobile data
- [ ] Each read-only share is readable and refuses writes; the vault accepts them (`kit check`: nas)
- [ ] The Claude API key works (`kit check`: claude)
- [ ] After closing every Ubuntu window and waiting five minutes, `ollama ps` in a new window still answers (Ubuntu stayed up)
- [ ] CI is green on Windows and Linux for this pull request
