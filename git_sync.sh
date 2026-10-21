#!/bin/sh
# =============================================================================
#  BoostLayer — git / GitHub automation (SSH).
#
#  * If there is no local repository yet: initialise it, create the remote
#    GitHub repo via `gh`, switch the remote to SSH, commit and push to `main`.
#  * If the repository already exists and has uncommitted changes: create a
#    date-stamped branch (update-YYYYMMDD-HHMMSS), commit and push it over SSH.
# =============================================================================
set -eu

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_OWNER="multicolor-rgb"
REPO_NAME="BoostLayer"
SSH_REMOTE="git@github.com:${REPO_OWNER}/${REPO_NAME}.git"

log()  { printf '\033[1;32m[git]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }

cd "$REPO_DIR"

# Ensure a sane identity so commits never fail on fresh machines.
git config user.name  >/dev/null 2>&1 || git config user.name  "$REPO_OWNER"
git config user.email >/dev/null 2>&1 || git config user.email "${REPO_OWNER}@users.noreply.github.com"

# ---------------------------------------------------------------------------
# Case 1: no repository yet.
# ---------------------------------------------------------------------------
if [ ! -d .git ]; then
  log "No local repository — initialising and publishing first commit to 'main'."

  git init -b main
  git add -A
  git commit -m "Initial commit: BoostLayer" || {
    warn "Nothing to commit yet; creating empty repository shell."
  }

  if command -v gh >/dev/null 2>&1; then
    if gh auth status >/dev/null 2>&1; then
      log "Creating remote repository with GitHub CLI..."
      gh repo create "${REPO_OWNER}/${REPO_NAME}" --public --source=. --remote=origin
    else
      warn "GitHub CLI is not authenticated — run 'gh auth login' first."
      warn "Adding SSH remote manually; remote repo must already exist."
      git remote add origin "$SSH_REMOTE"
    fi
  else
    warn "GitHub CLI ('gh') not found — adding SSH remote manually."
    git remote add origin "$SSH_REMOTE"
  fi

  # Force the SSH transport regardless of how gh configured origin.
  git remote set-url origin "$SSH_REMOTE"
  log "Remote set to: $SSH_REMOTE"

  git push -u origin main
  log "Pushed initial commit to 'main'."
  exit 0
fi

# ---------------------------------------------------------------------------
# Case 2: repository exists — publish uncommitted work on a dated branch.
# ---------------------------------------------------------------------------
if [ -z "$(git status --porcelain)" ]; then
  log "Working tree clean — nothing to publish."
  exit 0
fi

BRANCH="update-$(date +%Y%m%d-%H%M%S)"
log "Uncommitted changes detected — creating branch '$BRANCH'."

# Make sure the SSH remote is the configured origin.
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$SSH_REMOTE"
else
  git remote add origin "$SSH_REMOTE"
fi

git checkout -b "$BRANCH"
git add -A
git commit -m "Update $(date '+%Y-%m-%d %H:%M:%S')"
git push -u origin "$BRANCH"
log "Pushed new branch '$BRANCH' to GitHub over SSH."
