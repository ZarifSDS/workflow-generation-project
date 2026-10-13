"""Re-encrypt stored provider keys under the first key in STUDIO_SECRETS_KEY (ADR 0008).

Rotation: put the new key first in STUDIO_SECRETS_KEY (comma-separated, old key after it), restart,
run this command, then remove the old key from .env and restart again.
"""

from cryptography.fernet import InvalidToken
from django.core.management.base import BaseCommand, CommandError

from apps.ai import secrets
from apps.ai.models import ProviderConfig


class Command(BaseCommand):
    help = "Re-encrypt stored provider API keys with the first key in STUDIO_SECRETS_KEY."

    def handle(self, *args, **options):
        try:
            fernet = secrets._fernet()
        except secrets.SecretsUnavailable as error:
            raise CommandError(str(error)) from None
        count = 0
        for row in ProviderConfig.objects.all():
            for field in ("api_key_encrypted", "account_id_encrypted"):
                token = getattr(row, field)
                if not token:
                    continue
                try:
                    setattr(row, field, fernet.rotate(token.encode()).decode())
                except InvalidToken:
                    raise CommandError(
                        f"{row.name}: none of the keys in STUDIO_SECRETS_KEY decrypts it."
                    ) from None
                count += 1
            row.save(update_fields=["api_key_encrypted", "account_id_encrypted"])
        self.stdout.write(f"Re-encrypted {count} stored value{'s' if count != 1 else ''}.")
