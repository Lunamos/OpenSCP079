# Notice / Attribution

LunaMoth is a local-first agentic character tavern/runtime. The runtime source code is licensed under Apache License 2.0; see `LICENSE`.

The bundled example content — the LunaMoth 月蛾 and Quinn 小Q character cards with their embedded world books — is original, owner-authored content, licensed under Apache-2.0 together with the rest of the project.

Quinn's card mentions the "SCP Foundation" only as a personal hobby of the character. That brief fan-mention is not reproduced SCP article text and does not by itself constitute SCP-derived content requiring CC BY-SA attribution.

## Code adapted from other projects

- `src/lunamoth/transcript.py` adapts the SQLite storage design (WAL journal
  mode with a DELETE fallback for WAL-incompatible filesystems) from
  [hermes-agent](https://github.com/NousResearch/hermes-agent)'s
  `hermes_state.py`, © Nous Research, MIT License.
