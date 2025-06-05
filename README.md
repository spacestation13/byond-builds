# BYOND Build Mirror

## Overview

This repository mirrors the executable files from the [official BYOND website](https://www.byond.com/download/build/) for BYOND versions 515 and 516, making them available through GitHub Pages.

## Mirror Structure

The files are organized by their major version:

```
/515/515.XXXX_byond.exe
/516/516.XXXX_byond.exe
```

## Accessing the Mirrored Files

The files are available through GitHub Pages at:

```
https://spacestation13.github.io/byond-builds/{version}/{filename}
```

For example:
```
https://spacestation13.github.io/byond-builds/515/515.1647_byond.exe
```

## How It Works

A script is run manually to:

1. Check the official BYOND website for new builds
2. Download any new build files that are not already mirrored
3. Commit the new files to the repository
4. Deploy the updated files to GitHub Pages

## License and Attribution

This repository only provides a mirror of officially released BYOND software. All rights to the BYOND software belong to their respective owners.

This mirror is not affiliated with or endorsed by BYOND.
