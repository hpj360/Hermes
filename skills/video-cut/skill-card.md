## Description: <br>
End-to-end turn an unedited long-form talking-head, vlog, or podcast video into a compact first cut by downloading or using local media, transcribing, diagnosing slow sections, planning cuts, rendering with ffmpeg, and self-checking the result. <br>

This skill is ready for commercial/non-commercial use. <br>

## Publisher: <br>
[whitetowerai](https://clawhub.ai/user/whitetowerai) <br>

### License/Terms of Use: <br>
MIT-0 <br>


## Use Case: <br>
Developers, creators, and agent operators use this skill to turn raw talking-head, vlog, or podcast footage into a shorter rough cut with a structured edit plan, rendered output, and verification report. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: The workflow runs local video tooling and shell commands. <br>
Mitigation: Review commands before execution and run the workflow only in an environment where yt-dlp, ffmpeg, ffprobe, and Python dependencies are expected. <br>
Risk: The workflow can download and process user-provided or private video content. <br>
Mitigation: Avoid providing authenticated or private media access unless the local tools are intended to process that content. <br>
Risk: The workflow writes intermediate and output media files. <br>
Mitigation: Keep work paths project-scoped and review generated files before sharing or deployment. <br>


## Reference(s): <br>
- [ClawHub Skill Page](https://clawhub.ai/whitetowerai/skills/video-cut) <br>
- [Edit Coarse Schema](reference/edit_coarse.schema.md) <br>
- [Pitfalls and Fixes](reference/pitfalls.md) <br>


## Skill Output: <br>
**Output Type(s):** [guidance, shell commands, configuration, markdown, text] <br>
**Output Format:** [Markdown guidance with inline shell commands and JSON edit-plan configuration] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [May guide creation of project-scoped intermediate files, rendered media, and self-check reports.] <br>

## Skill Version(s): <br>
1.0.2 (source: server release evidence) <br>

## Ethical Considerations: <br>
Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment. <br>
