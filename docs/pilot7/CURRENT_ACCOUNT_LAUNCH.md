# Current-account runtime execution

The researcher explicitly authorized use of their current Windows account on 2026-11-23. The previous
bootstrap checked a hard-coded LitReviewPilot SID to enforce separate-account filesystem isolation. It did
not merely check a username. The replacement accepts any Windows account whose actual process token is not
elevated and is not running as an administrator. Token-query failures refuse execution. `python -I -S -B`
is required to disable user-site/editable import hooks and bytecode writes.

Every launch still verifies the immutable runtime inventory, restricts execution to inventoried source,
refuses redirected provider endpoints and preserves all pipeline spending and scientific checkpoints. The
builder now exports the versioned bootstrap from Git rather than copying an old account-bound bootstrap.
Existing sealed runtimes are never modified.

Credentials may come from the current process or an explicitly named .env file inside the current account's
profile. Only ANTHROPIC_API_KEY, OPENAI_API_KEY and MOONSHOT_API_KEY are loaded into process memory. Existing
process keys win. No credential value, preview, hash or file content is logged or copied into the runtime.
Presence and source metadata are safe to report. Endpoint-redirection entries in that file refuse execution.
No credentials from another Windows account are accessed.

This does not reproduce separate-account ACL isolation. The current account may access development Git
history, historical scientific outputs and personal files. Integrity checks protect the runtime source;
they cannot deny the account access to other files. The execution bundle remains allowlisted and the new run
imports no earlier approvals or scientific outputs. This limitation is explicit, not represented as an ACL
test that passed.

The live pilot retains its explicit $50 combined maximum, $1 smoke authorization, $25/$48 review pauses,
disabled automatic alternate-model routes, dispatch receipts and every scientific checkpoint. No checkpoint
approval or model substitution is implemented by the bootstrap.
