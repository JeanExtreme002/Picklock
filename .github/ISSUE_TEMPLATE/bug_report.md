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
$ picklock
picklock> ps:open 91434
Attached to process.exe (PID 91434, 64-bit). (0.00 sec)
picklock> ...
```

**Expected behavior**
A clear and concise description of what you expected to happen instead.

**Versions**
Paste the output of `picklock --version` — it covers Picklock, PyMemoryEditor,
Python and the platform:

```
       Picklock: 0.1.0
PyMemoryEditor: 2.2.0
        Python: 3.12.0
      Platform: Linux 6.8.0 (x86_64)
```

**Environment**
- Were you running elevated (`sudo` / Administrator)? [yes / no]
- Terminal (e.g. Windows Terminal, iTerm2, GNOME Terminal, plain SSH):
- On Linux, the value of `/proc/sys/kernel/yama/ptrace_scope`:
- Target process (e.g. a game, browser, another script), if that matters:

**Additional context**
Add any other context about the problem here. If the target was a process you
cannot share, a minimal script that reproduces the same behaviour helps a lot.
