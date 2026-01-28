# BYOND Build Mirror

## Overview

This repository mirrors the downloadable installers and portable files from the [official BYOND website](https://www.byond.com/download/build/), hosted on Cloudflare R2.

## Mission Statement
This repository aims to mirror BYOND versions that are relevant to the larger SS13 community. 
For example, having a link for your players to download the recommended version of BYOND to play your servers on.
This repository does not aim to provide an archive of every BYOND version ever.

'BYOND versions that are relevant' is defined as:
* The current version.txt, denoting the latest `major.minor` version and possibly the latest beta version on the next line.
* The last 2 stable major versions, including all minor versions.
* If there is a current beta version, all minor versions.

Additional versions are not supported due to:
* GitHub repository size limits.
* Maintainer overhead.
* I don't really want to encourage people to use ancient BYOND versions.

The files available are: `XXX.YYYY_byond.exe`, `XXX.YYYY_byond.zip`, `XXX.YYYY_byond_linux.zip`.

`YYYY` can also be `latest` for the highest minor version of the major. For example, `515.latest_byond.exe`.

`_byondexe.zip` and `_byond_setup.zip` are deemed not relevant.

## Accessing the Mirrored Files

The files are available at:

```
https://byond-builds.dm-lang.org/{version}/{filename}
```

For example:
```
https://byond-builds.dm-lang.org/515/515.1647_byond.exe
```

This follows the same format as BYOND does.

## How It Works

The scripts in this repository are run manually to:

**Download**: `py .\scripts\download_byond_builds.py` checks the official BYOND website for new versions and downloads them locally.

**Upload**: `py .\scripts\upload_to_r2.py` uploads the relevant files to Cloudflare R2

Currently, attempts to automate the downloading process to happen via GitHub actions has been foiled.

## Disclaimer & Warranty

* This README describes the supported offerings of the service.
* This repository may be force-pushed and squashed to a single commit at any time.
  * One reason for this to possibly occur is if GitHub requests we decrease our repository size.
* A minimum of one month of notice will be given for any breaking changes.
  * Yes, this includes removing the n-3 BYOND version.
* It's common for BYOND versions to be completely broken. This mirror does not differentiate between broken versions in any way.
* Some BYOND versions lack linux releases, as they're client-only. These can be identified by the lack of the `byond_linux.zip`.
* I reserve the right to deal with active malicious abuse of the mirror as I see fit.
* All these policies can change at any time, please contact `ZeWaka` on Discord if you seek changes.
 
For additional warranty and disclaimer information, please see the [LICENSE](./LICENSE).

## License & Attribution

This repository only provides a mirror of officially released BYOND software.

This mirror is not affiliated with nor endorsed by BYOND.

All `.zip` and `.exe` files in this repository are the property of [BYOND Software](https://www.byond.com/).

All rights to these files belong to their respective owners.

All other files are [licensed under](./LICENSE) the MIT license.

---

## Internal - Adding a New BYOND Major Version

When BYOND releases a new major version, update the following:

1. **`scripts/download_byond_builds.py`** - Add to `BASE_URLS` dict

2. **`scripts/upload_to_r2.py`** - Add to `BASE_VERSIONS` list

3. **`public/index.html`** - Add version section in the HTML body and JavaScript