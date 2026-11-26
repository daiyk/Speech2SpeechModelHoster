# Experiment check

Run this with the Mac, client device, room, language, personality, and tool settings intended for the experiment. A successful server connection is the starting point.

## Record the configuration

- Date and experiment/session identifier.
- Mac model, chip, memory, macOS version, and power source.
- This repository's commit and the installed `speech-to-speech` version.
- Pipeline configuration and selected model IDs; preserve model/cache revisions if exact reruns are needed.
- Client application and device software versions.
- Conversation language, personality instructions, enabled tools, and memory settings.
- Local or LAN connection, network, speaker volume, and microphone placement.

Package versions are locked by this repository. Model IDs alone do not freeze Hugging Face model contents; record the cached revisions used for a study.

## Prepare

- [ ] Install the environment and load all models while online.
- [ ] Run the endpoint check with a free conversation slot, then close the diagnostic client.
- [ ] Connect the intended client to the local endpoint and complete a spoken exchange.
- [ ] Restart the server and client to verify the saved connection settings.
- [ ] If offline operation is required, repeat a full conversation without internet access while retaining the local network.
- [ ] Keep the Mac powered and awake for the session.

## Test representative conversations

Use 30–50 representative turns, including short replies, long questions, and the longest expected conversation history. Decide the acceptable response delay and failure rate for the study before collecting measurements.

Record server timing and measure the first audible reply on the client. Network and playback delays contribute to the time the user experiences.

Record for each turn:

| Item | Record |
|---|---|
| Input | Prompt category and utterance duration |
| Recognition | Correct / minor error / meaning-changing error |
| Delay | End of participant speech to first audible reply |
| Response | Appropriate / incorrect / missing |
| Audio | Clear / clipped / stuttering / echo |
| Tools | Expected action and observed result, if applicable |
| Recovery | Any retry, reconnection, or operator intervention |

Separate the first cold-start turn from warmed-up turns. Report median, 95th-percentile, and maximum delay, plus failure and intervention counts. Do not use an estimated hardware throughput figure as the measured conversation delay.

## Exercise failure and interruption paths

- [ ] Interrupt a long response and confirm that playback stops and the next utterance is handled correctly.
- [ ] Speak with the planned background noise and microphone placement.
- [ ] Test silence, very short utterances, and a longer pause within an utterance.
- [ ] Trigger each client tool required by the experiment and confirm its result.
- [ ] Validate camera reasoning separately if the experiment needs it; it is not established by a speech-only check.
- [ ] Run a full-length session and watch for worsening latency or memory pressure.
- [ ] Restart after Mac sleep or a network disconnect and verify reconnection.
- [ ] Have the intended operator start and stop the system using the launcher and written instructions.

Write down the observed limits and the recovery steps before participant sessions. Retest after changing models, prompts, language, audio settings, or package versions.
