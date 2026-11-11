# VS Code bridge

This extension opens the local Code Studio and chat from VS Code. It has no runtime or development dependencies and does not bundle a packaging tool.

The previously declared `@vscode/vsce` development dependency pulled in Microsoft's `vsce-sign` packages, whose proprietary EULA is not on this repository's dependency allowlist. It was removed rather than granted an exception. Extension packaging is intentionally external: use a packaging tool whose license you have reviewed, and do not add proprietary signing binaries to this repository.

The extension connects only to the loopback API. See the repository [README](../../README.md) and [license policy](../../docs/LICENSING.md).
