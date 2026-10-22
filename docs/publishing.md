# Publishing to YouTube (V1.0)

A creator connects their YouTube account once, then publishes any rendered short from the
editor with metadata they review. PeakSift uploads with Google's resumable protocol, never
creates the same video twice, and reports only what actually happened. Operator setup:
[youtube-setup.md](youtube-setup.md).

## Pieces

| Piece | Where |
| --- | --- |
| Connection (one per user, encrypted refresh token) | `app/models/publishing_connection.py`, `app/services/publishing/connections.py`, `tokens.py` |
| OAuth (state, PKCE, consent URL, code exchange, revoke) | `app/services/publishing/youtube_oauth.py`, `app/api/publishing.py` |
| Publish job (metadata, statuses, fingerprint) | `app/models/publish_job.py`, `app/services/publishing/metadata.py`, `jobs.py` |
| Provider contract, YouTube and fake providers | `provider.py`, `youtube.py`, `fake.py`, `factory.py` |
| Resumable upload loop and pipeline | `uploader.py`, `pipeline.py`, `app/workers/publish_tasks.py` |
| API | `app/api/publish_jobs.py` (`/edits/{id}/publish`, `/publish-jobs/{id}`) |
| UI | `frontend/components/app/settings-view.tsx`, `components/app/editor/publish-dialog.tsx`, `lib/publishing*.ts` |

## OAuth security

- **Least privilege.** The only scope is `https://www.googleapis.com/auth/youtube.upload`: it
  can upload videos and nothing else — not read, edit or delete them, not see the channel.
  No OpenID, profile or email scope is requested; the only cost is that the channel's name
  is learned from the first upload's response instead of up front. Since V1.4 a creator can
  separately grant read-only analytics access (`youtube.readonly` + `yt-analytics.readonly`);
  publishing still requests upload-only access tokens, and a partial grant never changes the
  connection — see [performance-analytics.md](performance-analytics.md#permission-an-explicit-read-only-upgrade).
- **Authorization code flow with PKCE (S256)**, `access_type=offline` and `prompt=consent`
  so Google issues a refresh token; Google's official `google-auth-oauthlib` builds the
  request and performs the exchange.
- **State.** 32 random bytes, stored only as a SHA-256 hash together with the PKCE verifier
  (encrypted), bound to the user who started, valid for 10 minutes, and **deleted atomically
  on first use** (`DELETE … RETURNING`). A replayed, forged, expired or another user's state
  is refused *before* any exchange; starting again replaces a pending state. Starting is a
  `POST` (another site cannot start it with the user's cookie) and is rate limited.
- **Callback.** Requires the signed-in user that started; exchanges the code server-side;
  checks that the upload scope was granted and a refresh token issued; always answers `303`
  to the configured frontend's fixed `/settings` page with an allow-listed outcome code —
  there is no redirect parameter to abuse — with `Referrer-Policy: no-referrer` and
  `no-store`.
- **Tokens.** Only the refresh token is kept, encrypted with **AES-256-GCM** (`cryptography`)
  under `PUBLISHING_TOKEN_ENCRYPTION_KEY`; the associated data binds each ciphertext to its
  user, provider and key version, so a token copied to another row cannot be opened. Access
  tokens are obtained per job through `google-auth` and never stored. Tokens, codes,
  verifiers, client secrets and upload session URIs never appear in responses, URLs, the
  frontend or logs (logs are redacted as a second line of defence).
- **Disconnect** revokes the token with Google (best effort) and always deletes it locally,
  telling the user whether Google confirmed.
- **Revoked or expired consent** (Google's `invalid_grant`, or a token no configured key
  opens) fails the job with `authentication_required` and marks the connection
  `needs_reconnect`; Settings and the publish dialog then offer **Reconnect**.

## Publishing a short

1. `GET /edits/{id}/publish` gives the dialog its prefill — the clip candidate's own title and
   hook (no AI), **private**, no tags — plus the connection state and this edit's history.
2. `POST /edits/{id}/publish` validates the reviewed metadata by YouTube's rules and refuses
   (`422`, naming the field) rather than truncating: title 1–100 characters, description ≤
   5000 bytes, tags ≤ 500 characters as YouTube counts them (≤ 50 tags, no duplicates), no
   `<`/`>` or control characters; privacy `private`/`unlisted`/`public`; a made-for-kids
   declaration. Only a **READY** edit whose file exists, through a **connected** account.
3. A SHA-256 **fingerprint** over the connection, edit and metadata makes the request
   idempotent: the same request — even sent twice at once — returns the existing job.

## The pipeline

```
queued → preparing → uploading → uploaded → processing → published
                                        ↘ failed (retryable)   ↘ provider_failed
```

- **Session first.** The resumable session URI is created and **stored encrypted before a
  single byte is sent**; bytes stream from storage by ranged reads in chunks of
  `YOUTUBE_UPLOAD_CHUNK_BYTES` (multiples of 256 KiB, as Google requires).
- **Resume, never duplicate.** The loop first asks YouTube how many bytes it has (`PUT
  Content-Range: bytes */total`) and always continues from YouTube's confirmed offset. A
  killed worker, a crash right after the last byte, a retry or a redelivered message all
  resume the same session — YouTube reports the existing video — so one job never creates
  two videos; a job with a video id is never uploaded again. An expired session with no
  video yet is replaced once per attempt.
- **Real progress** is the bytes YouTube confirmed, never decreasing. Every commit checks the
  attempt's fencing token; retries are bounded (five in a row, exponential backoff, only for
  network, rate-limit, provider and expired-session errors).
- **After the upload,** bounded countdown checks follow processing (`processing →
  published`, or `provider_failed` when YouTube rejects it). With the upload-only scope
  YouTube does not report processing, so a real YouTube job ends honestly at **uploaded**
  and the dialog links to YouTube Studio.
- **Errors** are normalized: `authentication_required`, `permission_denied`,
  `quota_exceeded`, `rate_limited`, `invalid_metadata`, `upload_session_expired`,
  `network_error`, `provider_error`, `processing_failed` — each with a plain message.
  **Retry** exists only for jobs that failed before a video existed (or stalled).

## Testing without Google

`PUBLISHING_PROVIDER=fake` (refused in production) swaps in an in-memory provider with
YouTube's resumable semantics; its uploads are labelled **simulated** and never get a
YouTube link. The test suite also drives the real YouTube provider against a mock of Google's
upload endpoints (`backend/tests/youtube_mock.py`) and fakes the OAuth exchange; CI has no
Google credentials and makes no Google calls.

## Limitations (V1.0)

- YouTube only. No TikTok, Instagram, Facebook or X; no scheduling, multi-platform posting,
  analytics, comments or thumbnails.
- PeakSift cannot edit or delete a published video or its metadata — use YouTube Studio.
- Unverified Google projects upload **private** videos only, and Google's default quota allows
  about six uploads a day (see [youtube-setup.md](youtube-setup.md)).
- Processing completion is not observable with the upload-only scope.
