# Taking notes

Say "take a note", "jot this down" or "add milk to my shopping list" and Kit
writes it as a plain markdown file in your notes folder on the NAS, where
Obsidian (or any editor) can open it. A note with the same title gets the new
text added at the end under the time, so a list stays one note. Each note is
also put in Kit's memory, so "what did I note about the dentist?" finds it.

The notes folder is `nas.vault`, the only place on the NAS Kit may write.
`nas.notes_folder` picks a folder inside it (for example `Inbox`); leave it out
to save at the top level.

## 1. Let the kit user write to the share

In DSM: **Control Panel → Shared Folder**, select your notes share, **Edit →
Permissions**, and tick **Read/Write** for `kit`. The photo and Family shares
stay read-only.

## 2. Mount it in Ubuntu

This uses the same `kit` login as the other shares (`/etc/kit-nas.cred`).
Change `Notes` to your share's name if it's different (it's case sensitive):

```
sudo mkdir -p /mnt/nas/notes
echo '//192.168.86.109/Notes  /mnt/nas/notes  cifs  credentials=/etc/kit-nas.cred,uid=1000,gid=1000,iocharset=utf8,_netdev,nofail,x-systemd.automount 0 0' | sudo tee -a /etc/fstab
sudo systemctl daemon-reload
sudo mount /mnt/nas/notes
ls /mnt/nas/notes
touch /mnt/nas/notes/.kit-test && rm /mnt/nas/notes/.kit-test && echo writable
```

If the share is a folder inside another shared folder, put the whole path in
the first column, for example `//192.168.86.109/home/Notes`. Mount error 13
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
- [ ] Next day, "what did I note about the bins?" → Kit finds it
