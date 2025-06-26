# BYOND Build Mirror

## Overview

This repository mirrors the downloadable installers and portable files from the [official BYOND website](https://www.byond.com/download/build/), making them available through GitHub Pages.

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

The files available are: `XXX.YYYY_byond.exe`, `_byond.zip`, `_byond_linux.zip`.

`_byondexe.zip` and `_byond_setup.zip` are deemed not relevant.

## Accessing the Mirrored Files

The files are available through GitHub Pages at:

```
https://spacestation13.github.io/byond-builds/{version}/{filename}
```

For example:
```
https://spacestation13.github.io/byond-builds/515/515.1647_byond.exe
```

This follows the same format as BYOND does.

## How It Works

The `./scripts/download_byond_builds.py` script is run manually to:

1. Check the official BYOND website for new builds
2. Download any new build files that are not already mirrored
3. Commit the new files to the repository
4. Deploy the updated files to GitHub Pages

Possible automation of the above will be explored again when BYOND.com is operational.

## Disclaimer & Warranty

* This repository may be force-pushed and squashed to a single commit at any time.
  * One reason for this to possibly occur is if GitHub requests we decrease our repository size.
* The above policies can change at any time, please contact @ZeWaka on Discord if you seek changes.
  * A minimum of one month of notice will be given for any breaking changes.
* It's common for beta BYOND versions to be completely broken and unable to compile SS13 codebases. This mirror does not differentiate between broken versions in any way.
* Some BYOND releases lack linux releases, as they're client-only. These can be identified by the lack of the `byond_linux.zip`.
 
For additional warranty and disclaimer information, please see the [LICENSE](./LICENSE).

## License & Attribution

This repository only provides a mirror of officially released BYOND software. All rights to the BYOND software belong to their respective owners.

The non-BYOND code in the this repository (the mirroring scripts and such) is [licensed under](./LICENSE) the MIT license.

This mirror is not affiliated with or endorsed by BYOND.
