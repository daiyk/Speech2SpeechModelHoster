# Publishing the macOS app

Each Git tag in the form `vMAJOR.MINOR.PATCH` publishes an Apple Silicon app
ZIP and a signed Sparkle update feed. GitHub and the in-app update window both
display the matching entry from [CHANGELOG.md](../CHANGELOG.md).

## Before the first tag

1. Create a **public** GitHub repository, add it as the `origin` remote, and enable GitHub Actions. The app reads the public release assets without asking users to sign in. The workflow takes the owner and repository name from GitHub.
2. On your Mac, run `openssl rand -base64 32 | pbcopy` once. Save the clipboard value in your password manager. In the repository’s **Settings → Secrets and variables → Actions → Secrets**, add it as a repository secret named `SPARKLE_PRIVATE_KEY`. Keep using the same key for all releases so installed copies can verify updates. The workflow derives and embeds the public key.
3. For first installs that pass Gatekeeper’s normal check, configure Apple signing below. With just the Sparkle secret, the workflow builds an ad-hoc-signed app. macOS may block opening that download.

## Push a release

The first desktop release is `v0.2.0`. Once the remote and secret are ready,
push the branch and the local tag:

```sh
git push -u origin main
git push origin v0.2.0
```

For the next release, add a heading such as `## v0.2.1 — 2026-11-26` at the top
of the changelog and list the changes below it. Commit the changes, then tag
the commit and push:

```sh
git tag -a v0.2.1 -m "v0.2.1"
git push origin main
git push origin v0.2.1
```

The tag determines the app’s bundle and display versions (`v0.2.1` becomes
`0.2.1` in macOS). The workflow verifies the signed ZIP and feed before
publishing the draft. If a run fails, fix the repository secret or transient
error and re-run the job from **Actions**. For changes to tagged source, use a
new version.

The app checks `releases/latest/download/appcast.xml` in this repository.
Keep the app ZIP and `appcast.xml` on each release. To verify the first live
update, install the first release in Applications, publish a higher version,
then select **Check for Updates… → Install Update** in the installed app.
Confirm the new version in **About Reachy Mini Speech**.

## Apple signing and notarization

Add these repository secrets to enable Developer ID signing, Apple notarization,
and stapling before the ZIP is signed by Sparkle.

| Secret | Value |
| --- | --- |
| `APPLE_CERTIFICATE_P12` | Base64 contents of a Developer ID Application certificate exported with its private key. Copy with `base64 -i developer-id.p12 | pbcopy`. |
| `APPLE_CERTIFICATE_PASSWORD` | Password used when exporting the .p12 file. |
| `APPLE_ID` | Apple Account email used for notarization. |
| `APPLE_TEAM_ID` | Developer team ID that issued the certificate. |
| `APPLE_APP_PASSWORD` | App-specific password created for this Apple Account. |

The release job imports the certificate into a temporary runner keychain. A
signing or notarization failure stops publication. [Apple notarization guide](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)

The updater uses the official Sparkle framework and release tools. The build
pins the download by version and SHA-256. [Sparkle documentation](https://sparkle-project.org/documentation/)
