# Repository guidance for agents

- If the user gives this repository URL and asks to install, update, or configure it, read `INSTALL.md` and perform that workflow using the current host agent's actual capabilities and skill directory.
- The reusable workflow is `daily-article-video/SKILL.md`. It uses agent-neutral Markdown plus local Python/FFmpeg helpers.
- Never write real credentials, media, transcripts, browser sessions, or screenshots into Git. Credentials belong in a private local configuration file or secure environment injection.
- For development, run `python3 -m unittest discover -s tests -v`. Tests must use temporary synthetic data and mocked service responses, without real API calls or platform actions.
- Preserve the final-publish and cleanup boundaries in the skill. Installation does not authorize publication, audio upload, paid service activation, or deletion of user media.
- Annotation cards explain only terms or phenomena actually mentioned in the speech; use concise encyclopedic prose and chest placement. Follow the skill’s annotation rules for copy length, layout, and user-requested review checkpoints.
