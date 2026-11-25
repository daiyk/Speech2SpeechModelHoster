# Publishing Speech2SpeechModelHoster

Pushing a tag in the form `vMAJOR.MINOR.PATCH` to `daiyk/Speech2SpeechModelHoster`
starts the macOS release workflow. It publishes a DMG containing **Reachy Mini Speech.app**
and the signed Sparkle feed used by installed copies. GitHub and the in-app
update window display the matching entry from [CHANGELOG.md](../CHANGELOG.md).

## Before the first tag

1. Check that `git remote get-url origin` points to `daiyk/Speech2SpeechModelHoster`. For a checkout without a remote, run `git remote add origin https://github.com/daiyk/Speech2SpeechModelHoster.git`.
2. Enable GitHub Actions. On your Mac, run `openssl rand -base64 32 | pbcopy` once and save the value in your password manager. Add it as the repository secret `SPARKLE_PRIVATE_KEY`. Installed copies use the corresponding public key to verify future updates, so keep the same key across releases. [Repository Actions secrets](https://github.com/daiyk/Speech2SpeechModelHoster/settings/secrets/actions)

This project distributes an ad-hoc-signed app without Apple notarization.
`SPARKLE_PRIVATE_KEY` is the only release secret to configure. The
[installation guide](../README.md#macos-app) covers the macOS first-launch prompt.

## Push a release

Once the remote and secret are ready, publish the local `v0.2.2` tag with
these commands.

```sh
git push -u origin main
git push origin v0.2.2
```

For the next release, add a heading such as `## v0.2.3 — 2026-11-26` at the top
of the changelog, using the release date, and list the changes below it. Commit
the changes, then tag the commit and push it.

```sh
git tag -a v0.2.3 -m "v0.2.3"
git push origin main
git push origin v0.2.3
```

The tag determines the app’s bundle and display versions (`v0.2.2` becomes
`0.2.2` in macOS). The workflow verifies the signed DMG and feed before
publishing the draft. If a run fails, fix the repository secret or transient
error and re-run the job from **Actions**. For changes to tagged source, use a
new version.

After publication, the app checks
`https://github.com/daiyk/Speech2SpeechModelHoster/releases/latest/download/appcast.xml`.
Keep the DMG and `appcast.xml` on each release. To verify the first live
update, install the first release in Applications, publish a higher version,
then select **Check for Updates… → Install Update** in the installed app.
Confirm the new version in **About Reachy Mini Speech**.

The updater uses the official Sparkle framework and release tools. The build
pins the download by version and SHA-256. [Sparkle documentation](https://sparkle-project.org/documentation/)
