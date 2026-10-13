# ADR 0006: Four studio roles and login rate limiting

- Status: Accepted
- Date: 2026-10-13

## Context

The studio is shared over the internet (ADR 0005). Until M8, any user who could open the Wagtail admin could approve every step, export, re-check providers and edit presets, and nothing slowed down password guessing on the public login page.

## Decision

- **Four roles as Wagtail groups**, chosen with the user: Writers (writing steps, briefs, runs), Editors (writing and editing steps, exports), Moderators (read runs; publish through Wagtail's workflow), Operators (providers, presets, recovering stuck steps). Four custom permissions on the studio app (`access_studio`, `review_writing_steps`, `review_editing_steps`, `operate_studio`) carry them; a data migration creates the groups and adds the permissions to Wagtail's existing Editors and Moderators groups.
- Permissions are enforced server-side in every studio view and run action (`apps/studio/permissions.py`); templates only hide what the user can't use. Superusers keep full access.
- **Login rate limiting with django-axes**: 5 failures per username *and* address lock that pair for 15 minutes; the client address is read from `X-Forwarded-For` with one trusted proxy hop behind Caddy.
- Minimum password length raised to 12.

## Consequences

- Admins assign people to groups in **Settings › Groups** / **Users**; the permissions can be adjusted there without code changes.
- django-axes 8.3.1 declares support up to Django 6.0; it was tested on 6.1 in this project (imports, lockout and the full suite). Re-check on each Django upgrade.
- A shared address (tunnel, office NAT) can't be used to lock everyone out, but an attacker gets 5 tries per username per address; strong passwords remain essential.
- New studio views must set `permission_required` (and `post_permission` for actions); new run actions must go through `permissions.can_act`.
