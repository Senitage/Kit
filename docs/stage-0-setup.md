# Stage 0 setup: the Windows GPU PC

This gets the PC with the RTX 2070 Super ready to run Kit. It stays on Windows for
the early stages; the Linux move comes later and needs no code changes.

Work through the steps, then run `kit check`. Stage 0 is done when every
checklist box at the bottom is ticked.

## 1. NVIDIA driver

Install the latest Game Ready or Studio driver from nvidia.com. Then, in a new
terminal:

```
nvidia-smi
```

It should list the RTX 2070 SUPER with 8192 MiB.

## 2. Python

Install Python 3.12 from python.org and tick "Add python.exe to PATH". Kit needs
3.11 or newer.

## 3. Ollama and the local model

Install Ollama for Windows from ollama.com. It runs in the tray and starts with
Windows. Then pull Kit's everyday model (about 5 GB):

```
ollama pull qwen3:8b
ollama run qwen3:8b "Say hello in five words"
```

While it answers, Task Manager's GPU tab should show dedicated GPU memory in use.

## 4. Tailscale

Install Tailscale on this PC, the desk PC and your phone, all signed in to the
same account. In the Tailscale admin console, rename this PC to `kit-server`
and make sure MagicDNS is on.

Check from the desk PC: `tailscale ping kit-server`. Check from the phone with
Wi-Fi off: the Tailscale app shows `kit-server` as connected.

## 5. Synology: a `kit` user

Kit gets its own NAS account, so the NAS itself enforces what Kit may touch.

1. DSM, Control Panel, User & Group: create a user `kit` with a strong password.
2. Control Panel, Shared Folder, then for each share Kit should read (photos,
   documents): Edit, Permissions, give `kit` **Read only**.
3. For the Obsidian vault folder: File Station, right-click the vault folder,
   Properties, Permission, Create: `kit`, **Read & Write**. Everything else
   stays read-only.
4. Give the NAS a fixed IP address (a DHCP reservation on your router), for
   example 192.168.1.50.

Windows uses one set of NAS credentials per server name. Your own login already
uses `\\NAS`, so Kit uses the NAS's **IP address** with the `kit` user's
credentials. Store them once, in a terminal on the GPU PC:

```
cmdkey /add:192.168.1.50 /user:kit /pass
```

Then use paths like `\\192.168.1.50\photo` in Kit's settings (step 7). When the
server moves to Linux, these become mount points instead.

## 6. Anthropic API key

1. At console.anthropic.com, create an API key for Kit.
2. Under Limits, set a monthly spend limit you're comfortable with.
3. Save the key in Kit's secrets folder after step 7 creates it. The file is
   `C:\ProgramData\Kit\secrets\anthropic_api_key`, containing just the key.
4. Lock the folder down so only you and Windows can read it:

```
icacls "C:\ProgramData\Kit\secrets" /inheritance:r /grant:r "%USERNAME%:(OI)(CI)F" "SYSTEM:(OI)(CI)F"
```

## 7. Install Kit and run the checks

```
git clone https://github.com/Senitage/kit
cd kit
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e .
kit init
```

`kit init` creates `C:\ProgramData\Kit` and a starter `config\settings.toml`.
Open that file and fill in the `[nas]` section, using single quotes:

```toml
[nas]
vault = '\\192.168.1.50\home\Obsidian'

[nas.read_only_shares]
photos = '\\192.168.1.50\photo'
documents = '\\192.168.1.50\home\Documents'
```

Then:

```
kit check
```

Every line should say PASS. The NAS check writes a tiny `.kit-write-test` file
and deletes it straight away, to prove the read-only shares really refuse writes
and the vault accepts them. The Claude check only looks up the model, so it
costs nothing.

## Stage 0 test checklist

- [ ] `nvidia-smi` shows the 2070 Super (`kit check`: gpu)
- [ ] Ollama answers, on the GPU, with tokens/s shown (`kit check`: ollama)
- [ ] The desk PC and phone reach `kit-server` over Tailscale, including from mobile data
- [ ] Each read-only share is readable and refuses writes; the vault accepts them (`kit check`: nas)
- [ ] The Claude API key works (`kit check`: claude)
- [ ] CI is green on Windows and Linux for this pull request
