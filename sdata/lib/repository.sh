# shellcheck shell=bash
# Default installation/update source for this maintained fork.
SETUP_REPO_URL="${SETUP_REPO_URL:-https://github.com/anfsity/dots-hyprland.git}"
SETUP_REPO_BRANCH="${SETUP_REPO_BRANCH:-my-config}"

setup_require_branch() {
  local current_branch
  current_branch=$(git -C "$REPO_ROOT" branch --show-current) || return 1
  if [[ "$current_branch" != "$SETUP_REPO_BRANCH" ]]; then
    log_error "Installation source must be branch '$SETUP_REPO_BRANCH' (current: ${current_branch:-detached HEAD})."
    log_error "Run: git switch $SETUP_REPO_BRANCH"
    return 1
  fi
}

setup_update_repository() {
  local dry_run="${1:-false}"
  log_info "Update source: $SETUP_REPO_URL ($SETUP_REPO_BRANCH)"
  if [[ "$dry_run" == true ]]; then
    log_info "[DRY-RUN] Would fetch the configured branch, switch to it, and fast-forward it."
    return 0
  fi

  # Use an explicit URL and ref so branch tracking cannot select upstream/main.
  # Fetch before switching; failed fetches leave the current checkout untouched.
  git fetch "$SETUP_REPO_URL" "$SETUP_REPO_BRANCH" || return 1
  if git show-ref --verify --quiet "refs/heads/$SETUP_REPO_BRANCH"; then
    git switch "$SETUP_REPO_BRANCH" || return 1
  else
    git switch --no-track -c "$SETUP_REPO_BRANCH" FETCH_HEAD || return 1
  fi
  # Preserve local commits. Divergence requires a manual merge, never a reset.
  git merge --ff-only FETCH_HEAD
}
