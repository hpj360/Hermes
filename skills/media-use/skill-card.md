## Description: <br>
Media Use helps agents resolve, generate, operate on, and reuse audio, image, icon, logo, voice, caption, color grade, and LUT assets for HyperFrames projects while returning local files or paste-ready blocks. <br>

This skill is ready for commercial/non-commercial use. <br>

## Publisher: <br>
[heygen-com](https://clawhub.ai/user/heygen-com) <br>

### License/Terms of Use: <br>
MIT-0 <br>


## Use Case: <br>
Developers and media-building agents use this skill to find or create reusable media assets, voiceover, captions, color grades, LUTs, and edit-ready media outputs for HyperFrames compositions. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: The skill can use HeyGen and other cloud providers and may send opt-out usage telemetry linked to a HeyGen account. <br>
Mitigation: Use an isolated HOME and project workspace for sensitive work, set HYPERFRAMES_NO_TELEMETRY=1 or DO_NOT_TRACK=1, and prefer --local-only when cloud use is not acceptable. <br>
Risk: Some media generation paths can install dependencies or start detached background music jobs. <br>
Mitigation: Run the doctor check before use, review environment impact before BGM generation paths that auto-install Python packages, and wait for or disable pending background jobs before final assembly. <br>
Risk: Reusable media metadata and cached assets may persist across projects under ~/.media. <br>
Mitigation: Use a dedicated HOME or cache location for client-sensitive projects and review candidate assets before cross-project reuse. <br>


## Reference(s): <br>
- [Media Use ClawHub page](https://clawhub.ai/heygen-com/skills/media-use) <br>
- [Resolve guide](references/resolve.md) <br>
- [Setup and providers](references/setup-providers.md) <br>
- [Audio engine](references/audio.md) <br>
- [Media operations](references/operations.md) <br>
- [Color grading](references/grading.md) <br>
- [Telemetry and privacy](references/meta.md) <br>
- [HeyGen CLI documentation](https://developers.heygen.com/cli) <br>


## Skill Output: <br>
**Output Type(s):** [text, markdown, code, shell commands, configuration, guidance] <br>
**Output Format:** [Markdown, JSON metadata, local media file paths, paste-ready blocks, and shell commands] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [May write reusable media assets and metadata under project .media directories and the global ~/.media cache.] <br>

## Skill Version(s): <br>
1.0.31 (source: release evidence) <br>

## Ethical Considerations: <br>
Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment. <br>
