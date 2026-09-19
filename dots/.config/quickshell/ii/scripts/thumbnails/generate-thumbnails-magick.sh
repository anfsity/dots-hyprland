#!/usr/bin/env bash

# Generate thumbnails for files using ImageMagick (Multi-process Parallel Version)
# Following the Freedesktop thumbnail spec.

set -u
export LC_ALL=C

MAX_JOBS="${PARALLEL_JOBS:-$(nproc 2>/dev/null || echo 4)}"

get_thumbnail_size() {
    case "$1" in
        normal) echo 128 ;;
        large) echo 256 ;;
        x-large) echo 512 ;;
        xx-large) echo 1024 ;;
        *) echo 128 ;;
    esac
}

usage() {
    echo "Usage: $0 [--size normal|large|x-large|xx-large] --file <path> | --directory <path>" >&2
    exit 1
}

urlencode() {
    local str="$1" bytes byte out=""
    bytes=$(printf '%s' "$str" | od -An -tx1 -v | tr -d ' \n')
    while [ -n "$bytes" ]; do
        byte=${bytes:0:2}
        bytes=${bytes:2}
        if [[ "$byte" =~ ^(2f|3[0-9]|4[1-9a-f]|5[0-9a]|6[1-9a-f]|7[0-9a]|21|27|28|29|2a|2d|2e|5f|7e)$ ]]; then
            out+=$(printf "\\x${byte}")
        else
            out+="%${byte^^}"
        fi
    done
    printf '%s' "$out"
}

md5() {
    printf '%s' "$1" | md5sum | awk '{print $1}'
}

is_supported_image() {
    local path="$1"
    case "${path,,}" in
        *.jpg|*.jpeg|*.png|*.webp|*.avif|*.bmp|*.svg)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

generate_thumbnail() {
    local src="$1" abs_path encoded_path uri hash out mtime im_uri
    abs_path="$(realpath -s "$src" 2>/dev/null)" || return 1
    is_supported_image "$abs_path" || return 1

    mtime="$(stat -c %Y "$abs_path" 2>/dev/null)" || return 1

    encoded_path="$(urlencode "$abs_path")"
    uri="file://${encoded_path}"
    hash="$(md5 "$uri")"
    out="$CACHE_DIR/$hash.png"

    if [ -f "$out" ]; then
        return 0
    fi

    mkdir -p "$CACHE_DIR" 2>/dev/null
    chmod 700 "$CACHE_DIR" 2>/dev/null || true

    im_uri="${uri//%/%%}"

    if magick "${abs_path}[0]" \
        -thumbnail "${THUMBNAIL_SIZE}x${THUMBNAIL_SIZE}>" \
        -set "Thumb::URI" "$im_uri" \
        -set "Thumb::MTime" "$mtime" \
        png:"$out" 2>/dev/null; then
        return 0
    fi
    return 1
}

# Parse arguments
SIZE_NAME="normal"
MODE=""
TARGET=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --file|-f)
            [[ $# -lt 2 ]] && usage
            MODE="file"
            TARGET="$2"
            shift 2
            ;;
        --directory|-d)
            [[ $# -lt 2 ]] && usage
            MODE="dir"
            TARGET="$2"
            shift 2
            ;;
        --size|-s)
            [[ $# -lt 2 ]] && usage
            SIZE_NAME="$2"
            shift 2
            ;;
        *)
            usage
            ;;
    esac
done

THUMBNAIL_SIZE="$(get_thumbnail_size "$SIZE_NAME")"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/thumbnails/$SIZE_NAME"

if [ -z "$MODE" ] || [ -z "$TARGET" ]; then
    usage
fi

case "$MODE" in
    file)
        if [ ! -f "$TARGET" ]; then
            echo "File not found: $TARGET" >&2
            exit 2
        fi
        if generate_thumbnail "$TARGET"; then
            printf '%s\n' "PROGRESS 1/1 FILE $(realpath -s "$TARGET")"
        else
            printf '%s\n' "PROGRESS 1/1"
        fi
        ;;
    dir)
        if [ ! -d "$TARGET" ]; then
            echo "Directory not found: $TARGET" >&2
            exit 2
        fi

        files=()
        for f in "$TARGET"/*; do
            [ -f "$f" ] || continue
            is_supported_image "$f" || continue
            files+=("$f")
        done

        total=${#files[@]}
        if [ "$total" -eq 0 ]; then
            exit 0
        fi

        FIFO="$(mktemp -u)"
        mkfifo "$FIFO"
        exec 3<>"$FIFO"
        rm -f "$FIFO"

        jobs_running=0
        completed=0

        for f in "${files[@]}"; do
            (
                real_f="$(realpath -s "$f")"
                if generate_thumbnail "$f"; then
                    echo "OK $real_f" >&3
                else
                    echo "FAIL $real_f" >&3
                fi
            ) &
            ((jobs_running++))

            if [ "$jobs_running" -ge "$MAX_JOBS" ]; then
                read -u 3 status target_file
                ((completed++))
                if [ "$status" = "OK" ]; then
                    printf '%s\n' "PROGRESS $completed/$total FILE $target_file"
                else
                    printf '%s\n' "PROGRESS $completed/$total"
                fi
                ((jobs_running--))
            fi
        done

        while [ "$jobs_running" -gt 0 ]; do
            read -u 3 status target_file
            ((completed++))
            if [ "$status" = "OK" ]; then
                printf '%s\n' "PROGRESS $completed/$total FILE $target_file"
            else
                printf '%s\n' "PROGRESS $completed/$total"
            fi
            ((jobs_running--))
        done

        exec 3>&-
        ;;
    *)
        usage
        ;;
esac
