"""Static safety rules for the commands a skill or doc teaches (fenced blocks):
no opt-out override, no usage polled in a loop, no expanding prompt string,
no secret in a prompt. Prints one line per violation (none: empty output).

    python3 tests/py/skill_rules.py <file.md>
"""

import re
import sys

text = open(sys.argv[1], encoding="utf-8").read()
bad = []
for _lang, body in re.findall(r"```(\w*)\n(.*?)```", text, re.S):
    for line in body.splitlines():
        code = line.split(" #", 1)[0]
        if re.search(r"(^|\s)--auto(\s|$)|AGENTKIT_PERMISSIONS=auto", code) and code.strip().startswith(("ak ", "AGENTKIT_")):
            bad.append("autonomy override: " + code.strip())
        if re.search(r"\b(while|until|watch)\b.*\bak (usage|pick)\b", code):
            bad.append("usage polled in a loop: " + code.strip())
        if re.search(r"ak run[^\n]*--\s*\"[^\"]*(\$\(|`)", code):
            bad.append("expanding prompt: " + code.strip())
        if re.search(r"ak run[^\n]*\$\{?[A-Z_]*(KEY|TOKEN)", code):
            bad.append("secret in a prompt: " + code.strip())
print("\n".join(bad))
