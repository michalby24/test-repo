import os
import re
import subprocess
import sys

BOT_COMMIT_MSG = "chore: enforce correct rc version"
BOT_FOOTER_TAG = "Release-As:"

def run_git_command(args, fail_on_error=True):
    try:
        result = subprocess.run(["git"] + args, stdout=subprocess.PIPE, text=True, check=fail_on_error)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None

def find_baseline_tag():
    # Try to find an existing RC tag
    rc_tag = run_git_command(["describe", "--tags", "--match", "v*-rc*", "--abbrev=0"], fail_on_error=False)
    if rc_tag:
        return rc_tag, False

    # Try to find a stable tag
    stable_tag = run_git_command(["describe", "--tags", "--match", "v*", "--exclude", "*-rc*", "--abbrev=0"], fail_on_error=False)
    if stable_tag:
        return stable_tag, True

    # No tags found (First tag scenario)
    print("INFO: No tags found. Assuming 0.0.0 baseline.")
    return None, True

def get_commit_depth(baseline_tag):
    """
    Counts the number of 'user' commits since the baseline tag.
    Filters out bot commits AND release commits to prevent infinite loops.
    """
    rev_range = f"{baseline_tag}..HEAD" if baseline_tag else "HEAD"
    
    raw_subjects = run_git_command(["log", rev_range, "--first-parent", "--pretty=format:%s"], fail_on_error=False)
    if not raw_subjects:
        return 0

    # Define patterns to ignore
    # 1. The bot footer we inject
    # 2. The bot message we inject
    # 3. Standard release-please commit messages (e.g., "chore(main): release 1.0.0-rc.1")
    # 4. Merge commits from release-please branches
    ignore_patterns = [
        BOT_FOOTER_TAG,
        BOT_COMMIT_MSG,
        r"^chore\(.*\): release", 
        r"^chore: release",
        r"Merge pull request .*from .*release-please"
    ]

    real_commits = []
    for s in raw_subjects.split('\n'):
        # Check if the commit matches any ignore pattern
        if any(re.search(pat, s) or pat in s for pat in ignore_patterns):
            continue
        real_commits.append(s)

    return len(real_commits)

# def get_commit_depth(baseline_tag):
#     """
#     Counts the number of 'user' commits since the baseline tag.
#     Filters out bot commits to prevent infinite loops.
#     """
#     rev_range = f"{baseline_tag}..HEAD" if baseline_tag else "HEAD"
    
#     raw_subjects = run_git_command(["log", rev_range, "--first-parent", "--pretty=format:%s"], fail_on_error=False)
#     if not raw_subjects:
#         return 0

#     # Filter out bot commits
#     real_commits = [
#         s for s in raw_subjects.split('\n')
#         if BOT_FOOTER_TAG not in s and BOT_COMMIT_MSG not in s
#     ]
#     return len(real_commits)

def parse_semver(tag):
    if not tag:
        return 0, 0, 0, 0

    # RC pattern
    m_rc = re.match(r"^v(\d+)\.(\d+)\.(\d+)-rc\.(\d+)$", tag)
    if m_rc:
        return int(m_rc[1]), int(m_rc[2]), int(m_rc[3]), int(m_rc[4])

    # Stable pattern
    m_stable = re.match(r"^v(\d+)\.(\d+)\.(\d+)$", tag)
    if m_stable:
        return int(m_stable[1]), int(m_stable[2]), int(m_stable[3]), 0

def analyze_impact(baseline_tag):
    rev_range = f"{baseline_tag}..HEAD" if baseline_tag else "HEAD"
    logs = run_git_command(["log", rev_range, "--pretty=format:%B"], fail_on_error=False)
    
    if not logs:
        return False, False

    breaking_regex = r"^(feat|fix|refactor)(\(.*\))?!:"
    is_breaking = re.search(breaking_regex, logs, re.MULTILINE) or "BREAKING CHANGE" in logs
    is_feat = re.search(r"^feat(\(.*\))?:", logs, re.MULTILINE)

    return bool(is_breaking), bool(is_feat)

def calculate_next_version(major, minor, patch, rc, depth, is_breaking, is_feat, from_stable):
    if is_breaking:
        return f"{major + 1}.0.0-rc.{depth}"
    
    if is_feat:
        if from_stable or patch > 0:
            return f"{major}.{minor + 1}.0-rc.{depth}"
        else:
            return f"{major}.{minor}.{patch}-rc.{rc + depth}"

    if from_stable:
        return f"{major}.{minor}.{patch + 1}-rc.{depth}"
    else:
        return f"{major}.{minor}.{patch}-rc.{rc + depth}"

def main():
    try:
        tag, from_stable = find_baseline_tag()
        
        depth = get_commit_depth(tag)
        if depth == 0:
            print("INFO: No user commits found since baseline. Exiting.")
            return

        major, minor, patch, rc = parse_semver(tag)
        
        is_breaking, is_feat = analyze_impact(tag)

        next_ver = calculate_next_version(
            major, minor, patch, rc, 
            depth, is_breaking, is_feat, from_stable
        )

        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"next_version={next_ver}\n")

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        # Fallback to release-please native
        sys.exit(0)

if __name__ == "__main__":
    main()
