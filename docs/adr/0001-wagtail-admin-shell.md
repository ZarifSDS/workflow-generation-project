# ADR 0001: Use the Wagtail admin as the application shell

- Status: Accepted
- Date: 2026-10-13

## Context

The tool needs authentication, forms, rich-text and structured content editing, revisions, an image library, approval workflows and publishing. Building these from scratch would take most of the project's time.

## Decision

Build on **Wagtail 8.0** (Django 6.1) and extend its admin through supported extension points rather than forking it:

- `register_admin_menu_item` and a custom `Menu` (`register_studio_menu_item`) for the "Content Studio" sidebar group
- `register_admin_urls` for custom views such as the run detail page
- `SnippetViewSet` / `ModelViewSet` for briefs, runs and prompt templates
- Wagtail Workflows and Tasks for final moderation
- Stimulus controllers via `insert_global_admin_js` for live step status
- StreamField for the published `ArticlePage`

Wagtail is installed from PyPI (`wagtail==8.0`), not vendored, so upgrades remain a version bump.

## Consequences

- Revisions, permissions, the image library and moderation come for free.
- Custom screens must follow Wagtail's admin conventions (templates extend `wagtailadmin/generic/base.html`).
- `wagtail-ai` (alpha, unverified on Wagtail 8) is not used; the studio has its own provider layer ([ADR 0003](0003-provider-registry.md)).
