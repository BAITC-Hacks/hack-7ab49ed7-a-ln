# Code rules (binding for both agents — Claude and Codex)

## Code

- Follow the style of the file you're editing; consistency beats preference.
- Small modules with explicit boundaries. Depend on interfaces at the edges (Telegram, DB, HTTP, queue) so they can be swapped and faked.
- Errors are typed and handled at the layer that can do something about them. No bare `except`, no `catch {}`, no log-and-continue when state may be left inconsistent.
- No shared mutable state across invocations, and no import-time side effects beyond constructing clients.
- No dead code, commented-out code, unimplemented stubs, or placeholder returns in finished work.
- API and schema changes are backward compatible or versioned. Migrations must be safe to run while the previous version is still serving.
- Avoid N+1 calls; batch and paginate. Measure before optimizing.
- Don't "simplify" by removing validation, auth checks, error handling, or types.

## Comments

The default is none; names, types, and structure should carry the meaning. Write a comment only for what the code can't say: a non-obvious why (a business rule, a legal constraint, a workaround for a dependency bug with the issue linked, a security or performance reason for an unusual choice), a hidden invariant or ordering dependency, or a pointer to the ADR, spec, or ticket being implemented.

Don't write narration of what the code does, banners or file headers, docstrings that restate the signature, commented-out code, `TODO`/`FIXME` without an owner and a ticket (`TODO(verify)` is the one exception), or notes explaining your reasoning; that belongs in the chat. If a block seems to need a "what" comment, extract a well-named function instead. Before finishing, reread the diff and delete every comment that fails this test.
