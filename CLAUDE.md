# CLAUDE.md

## SPECIAL.md (HIGHEST PRIORITY)

**Read and internalize `SPECIAL.md` at the start of every session.** It defines priority weights — where to invest extra scrutiny beyond standard professional practice. All stats at 5 = normal competence. Stats above 5 = extra focus.

This submodule has a single profile — all components share it:

**S6 P6 E7 C8 I9 A7 L5** — Shared library consumed by every other component.

Extra focus areas: Architecture (I9 — enforce boundaries, question scope creep, keep the API surface minimal), Clarity (C8 — naming, interface design, documentation — consumers depend on this being obvious), Agility (A7 — consumers pay for your weight).

See `SPECIAL.md` for full stat definitions and the priority allocation model.

## Interface Contract (PERSISTENT RULE)

**`COMMON_INTERFACE.md` is the authoritative contract for this package's public API.** Before changing any function signature, adding/removing exports, modifying config file schemas, or changing the root agent protocol, check the contract for consumers that depend on the current behavior. If a change breaks the contract, the contract must be updated and the main session notified so downstream consumers can adapt. Do not add provisioner-specific logic to common — common is hypervisor-agnostic.

## Rules

- After every code change and before pushing to GitHub, review and update documentation (README.md and DESIGN.md) if the changes affect any documented APIs, directory structures, usage examples, or architecture. Skip documentation updates only when the change has zero impact on anything documented.
