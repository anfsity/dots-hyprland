#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source $(eval echo $ILLOGICAL_IMPULSE_VIRTUAL_ENV)/bin/activate

# The GNOME thumbnailer is optional. If the GnomeDesktop GI namespace is not
# installed (which is the case on this system), fail quietly so the shell can
# fall back to generate-thumbnails-magick.sh instead of printing a traceback.
if ! python -c 'import gi; gi.require_version("GnomeDesktop", "4.0")' >/dev/null 2>&1; then
    deactivate
    exit 1
fi

GIO_USE_VFS=local "$SCRIPT_DIR/thumbgen.py" "$@"
THUMBGEN_EXIT_CODE=$?
deactivate

exit $THUMBGEN_EXIT_CODE
