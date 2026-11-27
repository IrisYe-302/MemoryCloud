# Accounts and shared albums

## First use

Open the app and choose a username and password (12–128 characters). The setup code is the server's `MEMORY_PASSWORD` value. On the current Mac demo it is `local-demo`. That code only authorizes creation of the first account; it is not a permanent login password or an open registration code. Existing photos, jobs and demo printers are assigned to the first account's album in one transaction. Nothing is deleted.

## Try sharing without a Pi

1. Sign in, scroll to the account panel, and open “Invite someone to this album”.
2. Choose an expiration and create a link. Copy it using the read-only field.
3. Open it in a private/incognito window on the same Mac. Create a different account, or sign in and choose “Join invited album”.
4. Both accounts can view, upload and remove photos in that album. Each can register a simulated printer. Only its owner can toggle its status or share it with another account.
5. Create a separate album and switch to it: photos and history from the other album are not exposed there. Your owned and explicitly shared printers remain available across albums.

Every invitation is single-use. Opening the page does not consume it; successful account creation or explicitly joining does. Only the album owner can create or revoke invitations. “Revoke unused links” does not remove members who already joined. Member removal is not implemented yet.

Printer registration here creates simulated printers, not QR-paired hardware. Registration creates a private destination for its owner. Use “Share printer” to grant another existing username access across albums, or revoke that access. Album membership alone does not grant printer access. Existing installations retain printer ownership but now require explicit sharing for other members. Revocation blocks new jobs; jobs already queued are unchanged. The two original demo printers belong to the first owner. Duplicate detection remains per printer, regardless of which member sends the photo.

## Technical boundaries

- Passwords use Werkzeug scrypt hashes. Session cookies are opaque random tokens; only their hashes are stored in SQLite. Sessions expire after seven days and logout invalidates them server-side.
- Mutations require the app's custom request header, reject cross-site requests, and validate Origin when present. Cookies are HttpOnly and SameSite=Lax; enable MEMORY_HTTPS=1 behind the trusted local TLS proxy for Secure cookies.
- Invitations are random 256-bit tokens stored as hashes, checked and consumed transactionally. URLs put tokens in the fragment; the UI removes that fragment after reading it into memory. Reloading before redemption requires reopening the original invite link.
- Login/registration are limited to 20 attempts per network address per 15 minutes. Behind the current proxy this may be shared across clients. No password recovery, MFA or member-removal workflow exists yet.
- The selected album is stored per login session as a default; each open tab scopes requests explicitly to its displayed album. Use separate browser profiles/private windows for different accounts.
- This is a private project prototype, not a fully audited public hosting service.

Tests cover account setup, session persistence and logout, invitation expiry/reuse/revocation, cross-origin rejection, album isolation and printer ownership, plus the original rendering and queue tests.

References: https://werkzeug.palletsprojects.com/en/stable/utils/#werkzeug.security.generate_password_hash and https://flask.palletsprojects.com/en/stable/web-security/

Removing a photo removes its membership in the selected album for all members. It does not delete the source file, other album memberships, or queued/completed print artifacts. Reuploading the original file can add it back.

## Public account creation

The sign-in page offers Create an account. Without an invitation, a new user receives an empty private album and no printer access. A valid invitation instead joins its album; invalid, expired or used invitations are rejected. Initial server claiming still requires the setup code.

## Photo contributions and edits

New uploads record their contributor and the date added to each album. Older photos with no recorded contributor display Original collection. Gallery sorting supports newest, oldest and contributor name. Color editing previews exposure, contrast, saturation and warmth, then saves a separate copy attributed to the editor. Originals and existing prints remain unchanged. Color controls affect saved album photos; thermal rendering controls affect only the print output.

### Duplicate review

Use **Find duplicates** in an album to compare up to 500 photos. Identical decoded pixels are labeled exact; conservative image-hash and color comparisons suggest similar copies. This is a heuristic and can miss changed crops or substantial edits. Exact extras are preselected, while similar photos require manual selection. Choose a photo to keep and confirm removal per group. Removal only unlinks selected copies from the current album for all its members; source files, other albums, and existing print jobs remain intact. Scanning never deletes anything.

## Display names

Signup has a separate name field. The name is used for greetings, member lists, and contributor labels. Usernames remain the login and printer-sharing identifier. Existing accounts without a profile use their username with the first letter capitalized. Profile names are stored separately so existing user records and passwords are preserved.
