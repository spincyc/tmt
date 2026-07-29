# Agent guidance

Read `tmt.json` before writing any script; never re-derive what a listed tool
already answers. Run `tools/<id>` directly — `--help` always works, and
`tools/<id>.md` carries the long doc when one exists. tmt is needed only to
make tools, never to run them.

When reasoning becomes repeatable, run `tmt note <slug>`. On its second
occurrence, scaffold with `tmt new <id>` and paste the derived logic. Prefer
editing the nearest existing tool over creating a near-duplicate. Keep the
registry honest with `tmt check`; it runs inside `make verify`.

aiq owns work state: capture requests, tasks, and outcomes there. Its own
guidance governs that system; none of it is duplicated here.
