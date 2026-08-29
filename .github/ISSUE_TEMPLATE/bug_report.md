---
name: Bug report
about: Create a report to help us improve
title: ''
labels: ''
assignees: ''

---

**Describe the bug**
A clear and concise description of what the bug is.

**To Reproduce**
The exact commands you ran, and what happened:

```console
$ peekmem
peekmem> open 1234
peekmem> ...
```

**Expected behavior**
A clear and concise description of what you expected to happen instead.

**Versions**
Paste the output of `peekmem -e "version"` — it covers Peekmem, PyMemoryEditor,
Python and the platform in one line:

```
Peekmem 0.1.0 / PyMemoryEditor 2.2.0 / Python 3.12.0 on Linux (x86_64)
```

**Environment**
- Were you running elevated (`sudo` / Administrator)? [yes / no]
- Terminal (e.g. Windows Terminal, iTerm2, GNOME Terminal, plain SSH):
- On Linux, the value of `/proc/sys/kernel/yama/ptrace_scope`:
- Target process (e.g. a game, another Python script), if that matters:

**Additional context**
Add any other context about the problem here. If the target was a process you
cannot share, a minimal script that reproduces the same behaviour helps a lot.
