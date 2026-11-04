# Face unlock with Gaze

The lock screen uses an independent PAM conversation for Gaze. Password and
fingerprint authentication keep their existing PAM conversations. Install Gaze,
start `gazed`, enroll the current user, and verify the camera with `gaze auth`.
The optional integration is enabled only when the `gaze` CLI is available.

The ii lock screen shows a themed status card above the password field, including
the initial delay, active scan, failed match with automatic retry, and unavailable
authentication. The Retry button starts a new scan immediately, including during
the automatic retry delay. Password entry stays available while scanning. The
card is hidden when face unlock is disabled or a power action is selected.
The card uses an opaque theme surface, a quiet status light and an animated scan
line. Retry stays in the header so the status text can wrap on narrow screens.

The face-only PAM stack lives in `pam/quickshell-face`; no change to the system
`login` PAM service is needed. Only an explicit successful match unlocks. Missing
enrollment, unavailable services, and failed scans cannot grant access.

Configuration in `~/.config/illogical-impulse/config.json`:

```json
{
  "lock": {
    "faceUnlock": {
      "enable": true,
      "startDelayMs": 2000,
      "retryDelayMs": 10000
    }
  }
}
```

Merge these keys into your existing configuration. Set `enable` to `false` to
turn off face unlock. Authentication starts after the compositor confirms the
session lock and the initial delay expires. Failed matches retry after the retry
delay so returning to an old lock screen still works. PAM errors stop automatic
retries; focusing the lock screen again permits another attempt. Submitting a
password cancels the face scan. Face authentication only unlocks the screen; it
does not authorize the password-protected power buttons.

Gaze confirmation prompts are not supported by this UI. If Gaze requests one,
the face conversation is cancelled and password authentication remains available.
For automatic face unlock, keep `auth.require_confirmation_lock_screen = false`
in Gaze's configuration (the default).

The default two-second delay gives you time to step away after locking. Increase
`startDelayMs` if a manual lock recognizes you before you have left the camera.
This delay is independent of Gaze's daemon-side delay.

From the repository root, run the isolated QML behavior checks with:

```sh
python3 tests/quickshell-face-unlock.py
```

Set `FACE_UNLOCK_ARTIFACTS=/tmp/face-unlock-preview` to retain PNG renders of the
Chinese status cards for visual inspection.

The checks require Qt 6 `qmltestrunner`. They replace PAM and process execution
with test doubles; hardware verification still requires a real lock/unlock.
