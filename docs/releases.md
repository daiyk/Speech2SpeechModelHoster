# Publishing Speech2SpeechModelHoster

Pushing a tag in the form `vMAJOR.MINOR.PATCH` to `daiyk/Speech2SpeechModelHoster`
starts the macOS release workflow. It publishes a DMG containing **Speech2SpeechModelHoster.app**
and the signed Sparkle feed used by installed copies. GitHub and the in-app
update window display the matching entry from [CHANGELOG.md](../CHANGELOG.md).

## Before the first tag

1. Check that `git remote get-url origin` points to `daiyk/Speech2SpeechModelHoster`. For a checkout without a remote, run `git remote add origin https://github.com/daiyk/Speech2SpeechModelHoster.git`.
2. Enable GitHub Actions. On your Mac, run `openssl rand -base64 32 | pbcopy` once and save the value in your password manager. Add it as the repository secret `SPARKLE_PRIVATE_KEY`. Installed copies use the corresponding public key to verify future updates, so keep the same key across releases. [Repository Actions secrets](https://github.com/daiyk/Speech2SpeechModelHoster/settings/secrets/actions)

This project distributes an ad-hoc-signed app without Apple notarization.
`SPARKLE_PRIVATE_KEY` is the only release secret to configure. The
[installation guide](../README.md#macos-app) covers the macOS first-launch prompt.

## Push a release

Once the remote and secret are ready, publish the local `v0.2.3` tag with
these commands.

```sh
git push -u origin main
git push origin v0.2.3
```

For the next release, add a heading such as `## v0.2.4 — 2026-11-26` at the top
of the changelog, using the release date, and list the changes below it. Commit
the changes, then tag the commit and push it.

```sh
git tag -a v0.2.4 -m "v0.2.4"
git push origin main
git push origin v0.2.4
```

The tag determines the app’s bundle and display versions (`v0.2.3` becomes
`0.2.3` in macOS). The workflow verifies the signed DMG and feed before
publishing the draft. If a run fails, fix the repository secret or transient
error and re-run the job from **Actions**. For changes to tagged source, use a
new version.

## Build an existing tag

Open **Actions → Release macOS app → Run workflow**, select **main**, and click
**Run workflow**. It builds the commit at the highest stable version tag (for
example, `v0.10.0` is newer than `v0.9.0`). [Release workflow](https://github.com/daiyk/Speech2SpeechModelHoster/actions/workflows/release.yml)

Push each new release tag individually. GitHub skips tag events when a single
push includes more than three tags. Updating the release workflow on `main` also
starts a build if the newest tag is still unpublished. [GitHub push events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#push)

## Verify a published update

After publication, the app checks
`https://github.com/daiyk/Speech2SpeechModelHoster/releases/latest/download/appcast.xml`.
Keep the DMG and `appcast.xml` on each release. To verify the first live
update, install the first release in Applications, publish a higher version,
then select **Check for Updates… → Install Update** in the installed app.
Confirm the new version in **About Speech2SpeechModelHoster**.

The updater uses the official Sparkle framework and release tools. The build
pins the download by version and SHA-256. [Sparkle documentation](https://sparkle-project.org/documentation/)
