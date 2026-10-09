# Your notes

Kit reads and writes your notes vault on the NAS (`nas.vault`), the only place on
the NAS Kit may write. Obsidian (or any editor) sees the same plain markdown files.

**Reading.** Every note in the vault is read into Kit's memory, split at its
headings, and kept in step every five minutes (new, changed and deleted notes).
Folders starting with a dot (`.obsidian`, `.trash`, `.SynologyWorkingDirectory`)
are skipped. Kit sees the names of your most recent notes, so "what's in my
holiday planner?" opens that note and answers from it, and "what did I write
about the bins?" searches all your notes. `kit notes` reads the vault now and
lists what Kit sees.

**Writing.** Say "take a note", "jot this down" or "add milk to my shopping
list". If a note with that name is anywhere in the vault, the new text goes on
the end under the time; otherwise it's a new note in `nas.notes_folder` (for
example `Inbox`), or in the folder you name ("put it in Projects").

Kit only writes a note when you ask for one. If something you say sounds worth
keeping but you didn't ask, he asks "want me to note that?" and saves it only if
you say yes.

## 1. Let the kit user write to the share

In DSM: **Control Panel → Shared Folder**, select your notes share, **Edit →
Permissions**, and tick **Read/Write** for `kit`. The photo and Family shares
stay read-only.

## 2. Mount it in Ubuntu

This uses the same `kit` login as the other shares (`/etc/kit-nas.cred`).
Change `Notes` to your share's name if it's different (it's case sensitive):

```
sudo mkdir -p /mnt/nas/notes
echo '//192.168.1.50/Notes  /mnt/nas/notes  cifs  credentials=/etc/kit-nas.cred,uid=1000,gid=1000,iocharset=utf8,_netdev,nofail,x-systemd.automount 0 0' | sudo tee -a /etc/fstab
sudo systemctl daemon-reload
sudo mount /mnt/nas/notes
ls /mnt/nas/notes
touch /mnt/nas/notes/.kit-test && rm /mnt/nas/notes/.kit-test && echo writable
```

If the share is a folder inside another shared folder, put the whole path in
the first column, for example `//192.168.1.50/home/Notes`. Mount error 13
means the `kit` user doesn't have permission yet (step 1).

## 3. Tell Kit where it is

```
kit config set nas.vault /mnt/nas/notes
kit config set nas.notes_folder Inbox      # optional
kit check
```

The `nas: vault` line should say PASS (writable). Settings apply from the
next message, so there's nothing to restart.

## Test checklist

- [ ] "Take a note: ring the council about the bins on Monday" → the chat shows
      "Saved ... in your notes" and the file is on the NAS
- [ ] "Add bread to my shopping list" twice → one `Shopping list.md` with both
- [ ] The note opens in Obsidian (or Notepad) on the PC
- [ ] `kit notes` lists your notes (not `.obsidian` or the Synology folders)
- [ ] "What's in my Holiday Planner?" → Kit opens it and answers from it
- [ ] "Add 'book the car' to my holiday planner" → it goes on the end of that note
- [ ] Edit a note in Obsidian, wait five minutes, ask about the change → Kit knows
- [ ] Next day, "what did I note about the bins?" → Kit finds it
