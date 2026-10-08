# Working together on BoardScope

GitHub holds the source code and changes. The application continues running locally on the lab PC; GitHub does not connect to the board or host the dashboard.

## Initial repository

Create a private repository named `boardscope`. If uploading this prepared source as the first commit, create it empty: no generated README, licence or .gitignore. Share its URL in the development conversation so changes can be pushed to the correct repository. Grant the connected GitHub app access to the repository when required.

Upload the contents of this folder at repository root, not the ZIP or its outer folder. Do not upload `.venv`, databases, passwords, SSH keys or board logs.

## Daily workflow

1. Pull the latest main branch on your lab PC before starting new work.
2. Describe a feature or bug with the relevant error and expected behavior, excluding passwords and proprietary evidence.
3. Implement changes on a feature branch and review the pull request. GitHub Actions checks the Python backend on Python 3.11 and 3.12 after push/PR events. These jobs do not use physical hardware.
4. After merging, stop the local application, pull main, install any changed requirements and restart BoardScope.
5. Run physical acceptance checks locally on the board and report the result.

Do not pull source changes into a running physical test. An interrupted run will not automatically replay board actions after restart.

## Next feature work

- SSH password login and session-only credentials are implemented in 0.2.
- UART login and fixed read-only identity verification are implemented in 0.2; broader prompt support and test execution remain next.
- Serial ownership shared correctly between command execution and log capture.
- Reboot observation, console re-login and changed boot-ID verification through UART.
- Optional credential persistence through an OS credential manager.

The remaining items are planned; implemented connection features are documented in README.md. Implement them in small reviewed changes with prompt, timeout, redaction and reconnect tests before trying real hardware.
