# Security Policy

## Reporting a Vulnerability

**Please do not open a public issue for a suspected vulnerability.** Use one
of the channels below instead so the impact can be assessed and a fix
prepared before details become public.

- **Preferred:** open a [private security advisory] on GitHub. This creates a
  private thread visible only to the maintainers and the reporter, supports
  CVE assignment, and lets us coordinate a disclosure timeline.
- **Alternative:** email `contact@jeanloui.dev` with subject
  `[Peekmem security]`.

When reporting, please include:

- Affected version(s) — the output of `peekmem -e "version"` covers Peekmem,
  PyMemoryEditor, Python and the platform.
- The exact command line or shell session that triggers it.
- A minimal reproducer, and the impact you observed.
- Any prerequisites (privileges, `ptrace_scope`, target process attributes).

## Scope

Peekmem is a *client*. It parses commands, formats results, and calls
[PyMemoryEditor], which performs every read, write and scan through OS-level
APIs. Vulnerabilities in the memory operations themselves therefore belong to
PyMemoryEditor — see [its security policy][pyme-security] — while everything
between the keyboard and that call belongs here.

That Peekmem needs elevated privileges, a debugger entitlement or a relaxed
`ptrace_scope` to attach to a process is documented in the README; those
requirements are not defects.

In scope:

- Command injection or unintended code execution from anything Peekmem parses:
  a command line, an address expression, a `source` script, a pointer-path
  file loaded with `ptrload`.
- A command writing to an address other than the one it reported, or reporting
  a write that did not happen (and the reverse).
- Path traversal or unintended file writes from `ptrsave` and friends.
- Leaking target memory contents into a place the user did not ask for —
  history files, logs, error messages.
- Crashes in the shell that leave a target process attached, modified or in a
  more permissive state than it started.

Out of scope:

- Using Peekmem against a target you are not authorized to inspect. That is a
  misuse question, not a defect.
- Anti-cheat evasion or cheating-detection bypass requests.
- Peekmem being able to read and write another process's memory *at all* —
  that is the entire purpose of the tool, and the OS is what gates it.
- Bugs in PyMemoryEditor's platform backends. Report those [upstream][pyme-security];
  if you are unsure which side a bug is on, report it here and it will be
  routed.

## Supported versions

Fixes land on the latest release. Peekmem follows the version of
PyMemoryEditor it depends on rather than pinning to an old one, so please
reproduce on the current release of both before reporting.

[private security advisory]: https://github.com/JeanExtreme002/Peekmem/security/advisories/new
[PyMemoryEditor]: https://github.com/JeanExtreme002/PyMemoryEditor
[pyme-security]: https://github.com/JeanExtreme002/PyMemoryEditor/blob/main/SECURITY.md
