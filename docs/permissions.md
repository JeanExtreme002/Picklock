# Permissions

Reading another process's memory is a privileged operation on every operating
system, and there is no way around that — it is the same barrier a debugger
faces, for the same reason. If `ps:open` is refused, Picklock says which case
you are in:

```
ERROR: ... Picklock needs permission to open the target — try running it as an
administrator (Windows), with sudo (Linux), or with the debugger entitlement (macOS).
```

Here is what each platform actually wants.

## Linux

Either run it privileged:

```bash
sudo picklock
```

Or grant the capability once, to the interpreter, and skip `sudo` from then on:

```bash
sudo setcap cap_sys_ptrace+ep $(readlink -f $(which python3))
```

```{admonition} What that grants
:class: warning

`cap_sys_ptrace` on the interpreter lets **any** Python script you run attach to
your other processes, not only Picklock. On a personal machine that is usually
the trade you want; on a shared one it is not. `sudo picklock` for the session
is the narrower option.
```

Some distributions additionally restrict attaching to processes that are not
children of the caller, through Yama:

```bash
cat /proc/sys/kernel/yama/ptrace_scope     # 1 on most desktops
sudo sysctl -w kernel.yama.ptrace_scope=0  # until reboot
```

`0` allows attaching to any process of the same user. Setting it permanently
belongs in `/etc/sysctl.d/`, and is a decision about the machine rather than
about Picklock.

## Windows

Run the terminal **as Administrator** to touch processes you do not own.
Processes you started yourself, from the same session, usually open without it.

A few processes stay closed regardless: anti-cheat and anti-malware software
routinely protects itself, and a protected process cannot be opened by anything
that lacks a kernel driver. That is the software working as designed.

## macOS

The hardest of the three, and the one where the answer is often "you cannot".

- **Processes you own**, started from your session: `sudo picklock` works.
- **Anything else**: System Integrity Protection requires the caller to carry
  the `com.apple.security.cs.debugger` entitlement, and an entitlement has to be
  baked into a signed binary. `sudo` alone does not supply it, which is why
  `sudo picklock` can still be refused with a Mach error.

The practical routes are to sign a Python binary with the entitlement and use
that interpreter, or to run the target under a debugger you already trust.
Neither is something Picklock can do for you.

```{admonition} This is why the test suite attaches to itself
:class: note

A process can always open *itself* — no entitlement, no `sudo`, on any of the
three platforms. That is what Picklock's end-to-end tests do, and it is also
how the screenshot in these docs is generated.
```

## Bitness

Not a permission, but it fails at the same moment. A 32-bit process read from a
64-bit Picklock (or the reverse) needs the pointer size to be right, and
Picklock reports whether it could determine it — `ps:info` shows
`Bitness certain`. When it cannot, it assumes the host's and says so;
`ps:open --strict-bitness` refuses instead, which is what a script should do.

## Only what you are allowed to

Picklock talks to other processes through OS-level APIs. Point it at processes
you own, or that you have explicit permission to inspect. Everything on this
page is about clearing a technical barrier on **your own machine** — it is not
advice for getting around one somewhere else.
