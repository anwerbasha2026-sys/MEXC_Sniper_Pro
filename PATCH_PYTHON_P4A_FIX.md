# GitHub Actions / p4a Python version fix

The failed build log showed:

`Build failed: python3 should have same version as hostpython3, 3.11.5 != 3.14.2`

The workflow was requesting `python3==3.11.5` while the pinned python-for-android commit resolved `hostpython3` to 3.14.2.

This release fixes the mismatch by:

- using the official `v2024.01.21` python-for-android release,
- removing the incompatible newer commit pin,
- explicitly requiring both `python3==3.11.5` and `hostpython3==3.11.5`,
- keeping the Android target at Python 3.11.5, which matches the selected p4a release.

The official p4a 2024.01.21 recipe declares Python 3.11.5, and the p4a documentation recommends matching `python3` and `hostpython3` versions explicitly.
