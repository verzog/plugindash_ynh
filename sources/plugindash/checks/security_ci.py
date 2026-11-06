"""Does the plugin use moodle-security-ci (the security lint, OSV and the gated release), and is it kept up?"""

from __future__ import annotations

import os
import re

from ..model import AMBER, INFO, OK, RED, Finding
from ..modes import MODE_A, plugin_mode
from ..moodle import normalise_tag, version_key
from ._ci import strip_comments
from ._util import ci_text, ci_workflows

ID = "security_ci"
TITLE = "Security CI"
DESCRIPTION = ("Info until the plugin runs moodle-security-ci. Once it does: amber if the security job, its pin or "
               "the release gate is incomplete; red if the latest release's test record is missing or doesn't pass.")
ORDER = 61

# What to do about each kind of problem: the first key found in the message wins; "" is the default.
FIX = {
    "doesn't run osv-check": "Copy the OSV step from moodle-security-ci's ci/github/moodle-ci-security-job.yml.",
    "doesn't run the blocking PHPMD": "Copy the PHPMD step from moodle-security-ci's moodle-ci-security-job.yml.",
    "pins moodle-security-ci": "Set SECURITY_CI_REF to the newest tag in moodle-ci.yml and release.yml, "
                               "and copy any new action pins.",
    "pin different": "Use the same SECURITY_CI_REF in moodle-ci.yml and release.yml.",
    "Release gate incomplete": "Follow step 6 of moodle-security-ci's README: copy templates/TESTING.md and "
                               "templates/tests/release/TEMPLATE.md, add '/TESTING.md export-ignore' to "
                               ".gitattributes, and replace release.yml with ci/github/release.yml.",
    "test record": "Fill in tests/release/<tag>.md (every box ticked, tester, date, Result: PASS), merge it, "
                   "and release again.",
    "is missing": "Re-run the release workflow's run for that tag; it attaches the .sha256 and the test record.",
}

_REF = re.compile(r"\bSECURITY_CI_REF\s*:\s*['\"]?([\w./-]+)")
_REPO = re.compile(r"github\.com/([\w.-]+/[\w.-]+?)(?:\.git)?(?=[\s'\"]|$)", re.M)
# [ \t], not \s: check-test-record.sh greps line by line, so a blank field must not borrow the next line.
_DATE = re.compile(r"^Date:[ \t]*[0-3]\d/[01]\d/20\d\d[ \t]*$", re.M)


def record_problems(text: str, tag: str) -> list[str]:
    """What check-test-record.sh would reject in tests/release/<tag>.md (the same rules, read as text)."""
    problems = []
    if tag not in "\n".join(text.splitlines()[:5]):
        problems.append(f"the heading doesn't name {tag}")
    if not re.search(r"^Result:[ \t]*PASS[ \t]*$", text, re.M):
        problems.append("no 'Result: PASS'")
    if not re.search(r"^Tester:[ \t]*\S", text, re.M):
        problems.append("no tester")
    if not _DATE.search(text):
        problems.append("no DD/MM/YYYY date")
    unticked = len(re.findall(r"^[ \t]*- \[ \]", text, re.M))
    if unticked:
        problems.append(f"{unticked} unticked item{'' if unticked == 1 else 's'}")
    elif not re.search(r"^[ \t]*- \[[xX]\]", text, re.M):
        problems.append("nothing ticked")
    return problems


def _latest_tag(repo, ctx, name):
    """Newest version tag of the moodle-security-ci repo, worked out once per run."""
    cache = ctx.extra.setdefault("security_ci_tags", {})
    if cache.get(name) is None:  # A failed lookup (None) is tried again for the next repo.
        tags = repo.repo_tags(name)
        versions = [t for t in tags or [] if re.fullmatch(r"v?\d+(\.\d+)*", t)]
        if versions:
            cache[name] = max(versions, key=lambda t: version_key(normalise_tag(t)))
    return cache.get(name)


def run(repo, plugin, ctx):
    workflows = ci_workflows(repo, ctx.cfg)
    # Comments stripped, so a commented-out step doesn't count as running.
    read = []
    for wf in workflows:
        text, missing, _ = ci_text(repo, wf)
        read.append((wf, strip_comments(text), missing))
    ci = next(((wf, text, missing) for wf, text, missing in read if "security-lint.php" in text), None)
    if ci is None:
        unreadable = [name for _, _, missing in read for name in missing]
        if unreadable:
            return [Finding(ID, INFO, f"Couldn't tell whether CI runs moodle-security-ci: {', '.join(unreadable)} "
                            "couldn't be read", incomplete=True)]
        return [Finding(ID, INFO, "moodle-security-ci isn't adopted yet (no security-lint job in CI)")]
    wf, text, unreadable = ci
    url = repo.file_url(wf.path)
    findings = []
    if unreadable:
        # The other steps may be in a shared workflow we can't see: say so rather than call them missing.
        findings.append(Finding(ID, INFO, f"{', '.join(unreadable)} couldn't be read, so the OSV and PHPMD steps "
                                "weren't checked", url, incomplete=True))
    else:
        if "osv-check.sh" not in text:
            findings.append(Finding(ID, AMBER, "The security job doesn't run osv-check.sh (known vulnerabilities)", url))
        if "phpmd-unused.xml" not in text:
            findings.append(Finding(ID, AMBER, "The security job doesn't run the blocking PHPMD unused-code rules", url))
        elif _allowed_to_fail(text, "phpmd-unused.xml"):
            findings.append(Finding(ID, AMBER, "The PHPMD unused-code step is allowed to fail (continue-on-error), so "
                                    "it doesn't block", url))
    findings += _pin_findings(repo, ctx, text, url)
    if repo.source == "github":
        findings += _release_findings(repo, plugin)
    if not findings:
        findings.append(Finding(ID, OK, "moodle-security-ci is set up and the latest release passed its gate", url))
    return findings


def _indent(line):
    return len(line) - len(line.lstrip())


def _allowed_to_fail(text, marker):
    """True if the step that mentions `marker`, or the job it's in, sets continue-on-error (true or an expression)."""
    lines = text.splitlines()
    at = next((i for i, line in enumerate(lines) if marker in line), None)
    if at is None:
        return False
    # The step is the nearest "- " item at or above the marker; its keys run until the indent drops back.
    step = next((i for i in range(at, -1, -1) if lines[i].lstrip().startswith("- ")), None)
    if step is None:
        return False
    indent = _indent(lines[step])
    end = next((i for i in range(step + 1, len(lines)) if lines[i].strip() and _indent(lines[i]) <= indent), len(lines))
    checked = lines[step:end]
    # The job's own keys (runs-on, continue-on-error...) sit at the indent of its "steps:" line.
    steps = next((i for i in range(step, -1, -1) if re.match(r"^\s*steps\s*:", lines[i])), None)
    if steps is not None:
        key = _indent(lines[steps])
        top = next((i for i in range(steps, -1, -1) if lines[i].strip() and _indent(lines[i]) < key), 0)
        bottom = next((i for i in range(steps + 1, len(lines)) if lines[i].strip() and _indent(lines[i]) < key),
                      len(lines))
        checked += [line for line in lines[top:bottom] if _indent(line) == key]
    pattern = re.compile(r"^\s*(-\s+)?continue-on-error\s*:\s*(true|\$\{\{)", re.I)
    return any(pattern.match(line) for line in checked)


def _release_workflow(repo, workflows):
    return next((w for w in workflows if os.path.basename(w.path).lower() in ("release.yml", "release.yaml")), None)


def _pin_findings(repo, ctx, text, url):
    findings = []
    pin = _REF.search(text)
    if pin is None:
        return findings  # Not pinned by tag (e.g. a fixed path): nothing to compare.
    source = next((m.group(1) for m in _REPO.finditer(text) if "security-ci" in m.group(1).lower()),
                  "verzog/moodle-security-ci")
    latest = _latest_tag(repo, ctx, source)
    if latest is None:
        # E.g. a GitLab plugin: its source can't read tags on GitHub. Not checked, rather than quietly OK.
        findings.append(Finding(ID, INFO, f"Couldn't look up {source}'s newest tag, so the {pin.group(1)} pin "
                                "wasn't compared", url, incomplete=True))
    elif version_key(normalise_tag(pin.group(1))) < version_key(normalise_tag(latest)):
        findings.append(Finding(ID, AMBER, f"CI pins moodle-security-ci {pin.group(1)}; {latest} is out", url))
    release = _release_workflow(repo, repo.workflows()) if repo.source == "github" else None
    release_text = strip_comments(repo.workflow_text(release) or "") if release else ""
    other = _REF.search(release_text)
    if other and other.group(1) != pin.group(1):
        findings.append(Finding(
            ID, AMBER, f"release.yml and the CI pin different moodle-security-ci tags ({other.group(1)} and "
            f"{pin.group(1)})", repo.file_url(release.path),
        ))
    return findings


def _release_findings(repo, plugin):
    findings = []
    # One finding for the whole step, so a plugin part-way through adopting gets one line, not four.
    missing = []
    release = _release_workflow(repo, repo.workflows())
    if release is None or "check-test-record" not in strip_comments(repo.workflow_text(release) or ""):
        missing.append("release.yml isn't the gated version")
    if repo.file("TESTING.md") is None:
        missing.append("no TESTING.md")
    if repo.file("tests/release/TEMPLATE.md") is None:
        missing.append("no tests/release/TEMPLATE.md")
    if not re.search(r"^/?TESTING\.md\s+.*export-ignore", repo.file(".gitattributes") or "", re.M):
        missing.append("TESTING.md isn't export-ignored")
    if missing:
        where = repo.file_url(release.path) if release else repo.html_url
        findings.append(Finding(ID, AMBER, f"Release gate incomplete: {'; '.join(missing)}", where))
    rel = repo.latest_release()
    if rel is None:
        return findings
    path = f"tests/release/{rel.tag}.md"
    record = repo.file(path, rel.tag)
    names = {a.get("name") for a in rel.assets}
    base = f"{plugin.get('component')}-{rel.tag}"
    gated = f"{base}-test-record.md" in names or f"{base}.zip.sha256" in names
    if record is None:
        if gated:  # The gate ran for this tag, so its record should be in the tag.
            findings.append(Finding(ID, RED, f"Release {rel.tag} has no test record ({path})", rel.url))
        else:
            findings.append(Finding(ID, INFO, f"Release {rel.tag} was made before the release gate (no {path})",
                                    rel.url))
        return findings
    problems = record_problems(record, rel.tag)
    if problems:
        findings.append(Finding(ID, RED, f"Release {rel.tag}'s test record doesn't pass: {'; '.join(problems)}",
                                repo.file_url(path, rel.tag)))
    # In-house (Mode A) plugins don't need release files, so missing ones are only a note there.
    level = INFO if plugin_mode(plugin) == MODE_A else AMBER
    for name in (f"{base}.zip.sha256", f"{base}-test-record.md"):
        if name not in names:
            findings.append(Finding(ID, level, f"Release {rel.tag}: {name} is missing", rel.url))
    return findings
