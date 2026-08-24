# v1 to v2 identity migration

Advanced AI Video Tools v2 uses these canonical identities:

| Surface | v1 | v2 |
| --- | --- | --- |
| Distribution | `ai-video-tools` | `advanced-ai-video-tools` |
| Import package | `ai_video_tools` | `advanced_ai_video_tools` |
| Primary CLI | `ai-video-tools` | `advanced-ai-video-tools` |
| GUI/application name | AI Video Tools | Advanced AI Video Tools |
| macOS bundle ID | unset in the Python-only v1 shell | `com.pastrypersonal5.advancedaivideotools` |
| Generated output prefix | `ai-` | `ai-` |

The old `ai-video-tools` command remains available as a deprecated alias during
v2. It writes its warning to stderr so JSON output on stdout remains valid.
The alias is scheduled for removal no earlier than v3.

v2 creates a new Qt application-data location. It does not import v1 settings.
On first v2 settings initialization on macOS, the application removes only the
identified v1 `settings.yaml` and `settings.json` files under the old
`AI Video Tools` application-data directory. It refuses symbolic links and
non-regular files, never follows links, and leaves unrelated files untouched.

Existing output videos, logs, caches, and failed workspaces are not renamed or
deleted by this identity change. v1 and v2 are not supported as side-by-side
runtime installations.

The repository is intended to move to `advanced-ai-video-tool` separately from
this source migration. Signing, notarization, and publication of the macOS
bundle require the release owner's Apple Developer credentials.
