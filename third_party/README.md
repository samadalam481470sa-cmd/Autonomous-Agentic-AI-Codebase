# Licensed upstream code

Third-party source snapshots are kept separate from first-party application
source. This ensures line counts and attribution do not imply original authorship.

The Monaco Editor source is retrieved from a pinned release commit by a
one-time GitHub Actions workflow. The snapshot must preserve `LICENSE.txt`
and `ThirdPartyNotices.txt` and should not be mistaken for new first-party
engineering work. Building the editor uses the corresponding npm package.

Review upstream dependency changes and security advisories before upgrading.
