"""Application settings, read from the environment (or a .env file in dev)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent
# repo root
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Empty means "use the local SQLite file" — see database_url_resolved below.
    database_url: str = ""

    # Signs the session cookie. Must be set in production.
    session_secret: str = "dev-only-insecure-secret"

    # How long a login lasts.
    session_days: int = 14

    # Set to 1 when serving over HTTPS so the cookie is marked Secure.
    # Render sets this for us via render.yaml.
    cookie_secure: bool = False

    # Where the built frontend lives. Served by FastAPI in production.
    static_dir: Path = ROOT_DIR / "frontend" / "dist"

    # --- Phase 2: Microsoft Graph ----------------------------------------
    ms_tenant_id: str = ""
    ms_client_id: str = ""
    ms_client_secret: str = ""

    # Comma-separated. Mail polled from these.
    monitored_mailboxes: str = ""

    # Staff forward stray mail here. Treated differently from the mailboxes
    # above: we dig the original customer out of the forwarded body, because
    # the sender is whichever colleague pressed Forward.
    forward_mailbox: str = ""

    # Addresses that send us customer mail while looking internal. The website
    # forms come from website@expertsvc.com — treat that as internal and every
    # form submission silently disappears.
    website_senders: str = "website@expertsvc.com"

    # Used to recognise our own staff. Mail from here is office chatter, not a
    # new customer request — with the exception of website_senders above.
    internal_domain: str = "expertsvc.com"

    # Outlook categories written back onto source mail. Empty disables the
    # write entirely, which also means the app never needs Mail.ReadWrite.
    outlook_category: str = ""
    outlook_category_handled: str = ""

    poll_seconds: int = 60

    # Ignore mail older than this many days at ingest. Matters on the FIRST
    # sync of a mailbox, which walks its entire inbox history — without a
    # cutoff the queue floods with years-old mail. 0 turns the cutoff off.
    ingest_max_age_days: int = 7

    def _csv(self, raw: str) -> list[str]:
        return [item.strip().lower() for item in raw.split(",") if item.strip()]

    @property
    def mailbox_list(self) -> list[str]:
        """Every mailbox the poller reads, forward address included."""
        boxes = self._csv(self.monitored_mailboxes)
        forward = (self.forward_mailbox or "").strip().lower()
        if forward and forward not in boxes:
            boxes.append(forward)
        return boxes

    @property
    def website_sender_list(self) -> list[str]:
        return self._csv(self.website_senders)

    @property
    def graph_configured(self) -> bool:
        return bool(self.ms_tenant_id and self.ms_client_id and self.ms_client_secret)

    @property
    def database_url_resolved(self) -> str:
        if self.database_url:
            # Render hands out postgres:// URLs; SQLAlchemy 2 wants postgresql://
            if self.database_url.startswith("postgres://"):
                return self.database_url.replace("postgres://", "postgresql://", 1)
            return self.database_url
        return f"sqlite:///{BACKEND_DIR / 'expert_inbox.db'}"


settings = Settings()
