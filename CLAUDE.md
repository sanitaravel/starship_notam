# CLAUDE.md

@AGENTS.md

## Claude Code notes

- PRs into `development` may be merged by Claude once `pytest` passes
  (`gh pr merge <n> --merge`). Never push to or merge into `main`.
- When asked to verify a source live, fetch it with the project's own
  fetcher and parser using `NOTAM_ENV_FILE=.env.test`, not ad-hoc scripts
  against the real `.env`.
- For a map card change, render one with the real data and look at the PNG
  before reporting it done.
