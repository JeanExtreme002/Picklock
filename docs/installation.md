# Installation

Picklock needs Python 3.10 or newer, and nothing else you have to build.

```bash
pip install picklock
```

That pulls in [PyMemoryEditor](https://pypi.org/project/PyMemoryEditor/), which
is pure Python on top of `ctypes` — no C compiler, no wheels to chase, no
native build step. The install works the same on a laptop and on a server you
reached over SSH.

Check it:

```bash
picklock --version
```

## Faster scans

Scanning is the one place where raw speed shows. The `speed` extra pulls in
NumPy, which PyMemoryEditor uses to vectorise the numeric comparison loop:

```bash
pip install "picklock[speed]"
```

Picklock needs no configuration to use it and behaves identically without it —
only slower on large regions. It is worth having when you scan multi-gigabyte
processes and pointless when you do not.

## From source

```bash
git clone https://github.com/JeanExtreme002/Picklock
cd Picklock
```

## Running it

```bash
picklock                 # the shell
python -m picklock       # the same thing, without the console script
```

The console script and the module entry point are the same program; the second
is useful when a virtualenv's `bin` is not on your `PATH`.

```{admonition} You will probably need privileges
:class: warning

Reading another process's memory is a privileged operation on every operating
system. If `ps:open` is refused, [Permissions](permissions.md) says what each
platform wants.
```
