# YouTube publishing — operator setup

PeakSift publishes finished shorts to a creator's own YouTube channel through Google's
official OAuth and the YouTube Data API v3. Publishing is **off** until an operator completes
the steps below; until then the editor shows no publish button and Settings says publishing
is not enabled.

## 1. Google Cloud project and API

1. In the [Google Cloud console](https://console.cloud.google.com/), create (or choose) a
   project for your PeakSift deployment.
2. **APIs & Services → Library → YouTube Data API v3 → Enable.**

## 2. OAuth consent screen

1. **APIs & Services → OAuth consent screen** (Google Auth Platform → Branding / Audience /
   Data access).
2. User type **External** (unless every creator is in your Google Workspace).
3. App name, support email and developer contact as your organisation.
4. **Scopes:** add exactly one — `https://www.googleapis.com/auth/youtube.upload`. PeakSift
   requests nothing else: no OpenID, profile or email scope, and no read, edit or delete
   access to channels or videos.
5. While the app is in **Testing**, add each creator's Google account under **Test users**.

## 3. OAuth client

1. **APIs & Services → Credentials → Create credentials → OAuth client ID.**
2. Application type **Web application**.
3. **Authorized redirect URI:** your API's callback, exactly — for the Compose stack
   `https://<your-host>/api/publishing/youtube/callback`; for local development
   `http://localhost:8000/publishing/youtube/callback`.
4. Copy the client id and client secret.

## 4. PeakSift configuration

Set these in the environment or your secret manager (never in Git; see
`backend/.env.example` and `deploy/.env.example`):

| Setting | Value |
| --- | --- |
| `YOUTUBE_PUBLISHING_ENABLED` | `true` |
| `GOOGLE_CLIENT_ID` | the `….apps.googleusercontent.com` id |
| `GOOGLE_CLIENT_SECRET` | the client secret |
| `GOOGLE_OAUTH_REDIRECT_URI` | the redirect URI registered above (set automatically by `deploy/docker-compose.prod.yml` from `PUBLIC_URL`) |
| `PUBLISHING_TOKEN_ENCRYPTION_KEY` | 32 random bytes, base64: `python -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"` |

The API and workers refuse to start if publishing is enabled with any of these missing or
malformed (the error names the setting, never its value). Restart the API and workers.

**Keep the encryption key safe:** it encrypts every stored refresh token. Losing it means
every creator must reconnect; leaking it together with a database copy exposes upload access.
To rotate, set a new key with a higher `PUBLISHING_TOKEN_KEY_VERSION` and move the old one to
`PUBLISHING_TOKEN_PREVIOUS_KEYS` (`1:<old key>`); tokens are re-encrypted as they are used.

## 5. What creators see

1. **Settings → YouTube → Connect YouTube** opens Google's consent page (upload access only).
2. After consent, Google returns to `/settings` with the outcome; the connection is shown,
   named after the channel once the first upload reports it.
3. In the editor, **Publish to YouTube** beside **Download short** opens the publish dialog.

## Google's restrictions you should know

- **Unverified apps upload private videos.** Google locks videos uploaded through API
  projects that have not passed its audit to **private** viewing, whatever visibility the
  creator chooses. PeakSift says so in the publish dialog. To publish unlisted or public
  videos for real, complete Google's
  [YouTube API audit](https://support.google.com/youtube/contact/yt_api_form) for your
  project.
- **Testing mode** limits consent to listed test users, and Google expires refresh tokens of
  apps in Testing after 7 days — creators then see "Reconnect" (the job fails with
  `authentication_required` and the connection is marked `needs_reconnect`).
- **Quota.** A project starts with 10,000 units a day and each upload (`videos.insert`) costs
  about 1,600, so roughly six uploads a day per project until Google grants more. When it is
  spent, jobs fail with `quota_exceeded` and can be retried the next day.
- **Processing status.** Reading a video's processing state needs a read scope PeakSift
  deliberately does not request, so a YouTube job ends at **Uploaded**; the dialog links to
  YouTube Studio for processing and visibility.

## Verifying a deployment

Use a test channel and **test-safe media you own** (no copyrighted footage or music), publish
**privately**, and confirm in YouTube Studio that exactly one video appeared with the reviewed
title, description, tags and privacy. Disconnect afterwards in Settings: PeakSift revokes the
token with Google and deletes it.
