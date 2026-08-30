# Finding and attaching to a process

Everything else needs a target, so this is always the first thing you do.

## Listing

```
picklock> ps:list
```

On its own it lists every process you can see, which on a desktop is hundreds
of rows. Give it a substring instead:

```
picklock> ps:list chrome
+-------+------------+
| PID   | NAME       |
+-------+------------+
| 41902 | chrome.exe |
| 41903 | chrome.exe |
+-------+------------+
2 rows in set (0.02 sec)
```

Matching is case-insensitive by default (`--case-sensitive` turns that off) and
the list is sorted by name; `--pid-sort` sorts by PID instead, which is the
better order when several processes share a name and you want the oldest.

Long lists page rather than scroll away — see [Paging](#paging) below.

## Attaching

```
picklock> ps:open 41902
Attached to chrome.exe (PID 41902, 64-bit). (0.00 sec)

picklock [chrome.exe:41902]>
```

The argument is a PID when it is all digits and a name otherwise, so
`ps:open chrome.exe` works too. When a name is ambiguous the command says so
rather than picking one:

```
picklock> ps:open chrome.exe
ERROR: More than one process matches the name "chrome.exe": [41902, 41903].
```

`--partial` matches a name as a substring, and `--pid` / `--name` force the
interpretation for the awkward case of a process whose name is all digits.

The prompt carries the target from here on. That is deliberate: `memory:write`
is not a command you want to run against the wrong process because you forgot
which one you attached to two hours ago.

### Bitness

Picklock reports whether the target is 32- or 64-bit, and `ps:info` says
whether it is *certain*:

```
picklock [chrome.exe:41902]> ps:info
            PID: 41902
           Name: chrome.exe
   Architecture: 64-bit
Bitness certain: yes
   Pointer size: 8 bytes
        Regions: 212
     Accessible: 6.8 GB
       Writable: 832.4 MB
     Executable: 6.5 MB
       Reserved: 385.0 GB
    Main thread: 259
```

Bitness decides the pointer size, which decides how pointer chains are walked.
When it cannot be determined, Picklock assumes the host's and says so;
`ps:open --strict-bitness` refuses to attach instead, which is what you want in
a script.

`Reserved` is address space the target has claimed but not backed with memory.
It is reported separately because it is usually enormous and is not something
you can read — see [Inspecting a target](inspecting.md#regions).

## Detaching

```
picklock [chrome.exe:41902]> ps:close
Detached. (0.00 sec)
```

Closing drops the scan results, the pointer paths and the cached memory map
along with the handle. The target itself is untouched: anything you wrote to it
stays written.

Attaching to a different process does the same thing implicitly. Quitting the
shell (`exit`, Ctrl+C or Ctrl+D) detaches too.

## Paging

Every listing takes the same three flags, with short forms:

```
ps:list --limit 5        (-l)  rows per page
ps:list --page 2         (-p)  which page
ps:list --all            (-a)  no paging at all
```

The footer says where you are, and spells out the command for the next page so
you do not have to work it out:

```
Showing 20 of 3184 rows — page 1 of 160 (1.42 sec)
Next page: scan:results --page 2
```

The default page size is the `limit` setting, which persists — see
[Aliases and settings](aliases-and-config.md).
