# Adapter Authoring

Adapters add repository-specific rules to the generic core workflow.

Keep adapters narrow:

- point to local rule files through `rule_files`;
- define slices and risk levels;
- define mechanical gates as `argv` arrays;
- use `when_paths` for gates that should run only when relevant files changed;
- make high-risk confirmation boundaries explicit.

Do not put private paths, company names, secrets, or business-domain scripts in
public examples.
