"""Security-group policy tests for terraform/main.

These guard two classes of bug that a plain `terraform validate` will not catch:

  * an ECS task reachable from the internet directly, bypassing the ALB (and with it
    TLS termination, access logs and any WAF), and
  * a task that can egress to any host on any port.

The checks are static - they read the .tf sources rather than planning - so they run in
CI with no AWS credentials.
"""

import os
import re

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_TF_DIR = os.path.join(_PROJECT_ROOT, "terraform", "main")

_WORLD = "0.0.0.0/0"

# Security groups attached to ECS tasks. Nothing on the internet may reach these.
_TASK_SECURITY_GROUPS = {"ecs_sg", "ecs_bg_sg"}

# The only ports the load balancer may accept from the outside world.
_ALB_INGRESS_PORTS = {80, 443}

# Every line under terraform/main that names the whole internet, and why it is safe.
# A new open CIDR anywhere fails this test until someone adds it here with a reason.
_REVIEWED_OPEN_CIDR_LINES = {
    (
        "ecs_api_service.tf",
        'api_alb_default_cidrs = local.api_internal ? [local.vpc_cidr] : ["0.0.0.0/0"]',
    ): (
        "Default ALB ingress for a public API - the stated purpose of the ecs_api_service "
        "trigger, and overridable per environment via API_ALLOWED_CIDRS. The ALB is the "
        "only internet-facing hop; tasks admit the ALB security group only."
    ),
    (
        "main.tf",
        'cidr_blocks = ["0.0.0.0/0"]',
    ): (
        "Baseline task egress, TCP 443 only, for ECR pulls, CloudWatch Logs, Secrets "
        "Manager and HTTPS APIs. Guarded by test_task_egress_baseline_is_https_only."
    ),
}


# ---------------------------------------------------------------------------
# Ingress
# ---------------------------------------------------------------------------
def test_task_security_groups_take_no_cidr_ingress():
    """Tasks accept traffic from the ALB security group, never from a CIDR."""
    offenders = [
        rule
        for rule in _security_group_rules()
        if rule.direction == "ingress" and rule.security_group in _TASK_SECURITY_GROUPS and not rule.sourced_from_group
    ]
    assert offenders == [], (
        "ECS task security groups must admit only the ALB security group. "
        f"CIDR-sourced ingress found: {[str(r) for r in offenders]}"
    )


def test_no_ingress_rule_hardcodes_the_internet():
    offenders = [rule for rule in _security_group_rules() if rule.direction == "ingress" and _WORLD in rule.cidrs]
    assert offenders == [], f"Ingress open to {_WORLD}: {[str(r) for r in offenders]}"


def test_alb_ingress_is_limited_to_web_ports():
    for rule in _security_group_rules():
        if rule.direction != "ingress" or rule.security_group in _TASK_SECURITY_GROUPS:
            continue
        assert rule.from_port in _ALB_INGRESS_PORTS and rule.to_port in _ALB_INGRESS_PORTS, (
            f"ALB ingress must be limited to ports {sorted(_ALB_INGRESS_PORTS)}, got {rule}"
        )


# ---------------------------------------------------------------------------
# Egress
# ---------------------------------------------------------------------------
def test_no_allow_all_egress_to_the_internet():
    offenders = [
        rule
        for rule in _security_group_rules()
        if rule.direction == "egress" and _WORLD in rule.cidrs and rule.protocol == "-1"
    ]
    assert offenders == [], f"All-protocol egress to {_WORLD}: {[str(r) for r in offenders]}"


def test_task_egress_baseline_is_https_only():
    """The one open-CIDR egress entry in the shared baseline must stay TCP/443."""
    text = _read_tf("main.tf")
    occurrences = [m.start() for m in re.finditer(re.escape(_WORLD), text)]
    assert occurrences, "expected the task egress baseline to reference the internet on 443"

    for idx in occurrences:
        attrs = _own_attributes(_enclosing_object(text, idx))
        assert attrs.get("protocol") == '"tcp"', f"baseline egress to {_WORLD} must be tcp, got {attrs}"
        assert attrs.get("from_port") == "443" and attrs.get("to_port") == "443", (
            f"baseline egress to {_WORLD} must be limited to 443, got {attrs}"
        )


# ---------------------------------------------------------------------------
# Catch-all inventory
# ---------------------------------------------------------------------------
def test_open_cidrs_appear_only_at_reviewed_sites():
    found = set()
    for filename in _tf_filenames():
        for line in _read_tf(filename).splitlines():
            if _WORLD in line:
                found.add((filename, line.strip()))

    expected = set(_REVIEWED_OPEN_CIDR_LINES)
    assert found == expected, (
        "Unreviewed use of the open internet CIDR in terraform/main.\n"
        f"  new/changed: {sorted(found - expected)}\n"
        f"  gone (drop it from _REVIEWED_OPEN_CIDR_LINES): {sorted(expected - found)}"
    )


# ---------------------------------------------------------------------------
# Rule extraction
# ---------------------------------------------------------------------------
class _Rule:
    """One ingress or egress rule, however it was declared in HCL."""

    def __init__(self, filename, security_group, direction, attrs):
        self.filename = filename
        self.security_group = security_group
        self.direction = direction
        self.protocol = _unquote(attrs.get("protocol") or attrs.get("ip_protocol") or "")
        self.from_port = _as_int(attrs.get("from_port"))
        self.to_port = _as_int(attrs.get("to_port"))
        self.cidrs = _quoted_strings(attrs.get("cidr_blocks") or attrs.get("cidr_ipv4") or "")
        self.sourced_from_group = bool(attrs.get("security_groups") or attrs.get("referenced_security_group_id"))

    def __repr__(self):
        return (
            f"{self.filename}:{self.security_group} {self.direction} "
            f"proto={self.protocol or '?'} ports={self.from_port}-{self.to_port} "
            f"cidrs={self.cidrs or '-'} from_sg={self.sourced_from_group}"
        )


def _security_group_rules():
    """Every rule declared inline on a security group or as a standalone rule resource."""
    rules = []
    for filename in _tf_filenames():
        text = _read_tf(filename)
        for header, body in _blocks(text):
            match = re.match(r'resource\s+"([^"]+)"\s+"([^"]+)"', header)
            if not match:
                continue
            resource_type, resource_name = match.groups()

            if resource_type == "aws_security_group":
                rules.extend(_inline_rules(filename, resource_name, body))
            elif resource_type in ("aws_vpc_security_group_ingress_rule", "aws_vpc_security_group_egress_rule"):
                direction = "ingress" if resource_type.endswith("ingress_rule") else "egress"
                attrs = _own_attributes(body)
                target = _referenced_group(attrs.get("security_group_id", ""))
                rules.append(_Rule(filename, target, direction, attrs))
    return rules


def _inline_rules(filename, security_group, body):
    """Inline ingress/egress blocks, including those wrapped in a `dynamic` block."""
    for header, inner in _blocks(body):
        direction = _inline_direction(header)
        if direction is None:
            continue
        if header.startswith("dynamic"):
            inner = next((b for h, b in _blocks(inner) if h.startswith("content")), "")
        yield _Rule(filename, security_group, direction, _own_attributes(inner))


def _inline_direction(header):
    match = re.match(r'(?:dynamic\s+")?(ingress|egress)"?', header.strip())
    return match.group(1) if match else None


def _referenced_group(expression):
    match = re.search(r"aws_security_group\.(\w+)", expression)
    return match.group(1) if match else "?"


# ---------------------------------------------------------------------------
# Minimal HCL scanning
# ---------------------------------------------------------------------------
def _tf_filenames():
    return sorted(f for f in os.listdir(_TF_DIR) if f.endswith(".tf"))


def _read_tf(filename):
    with open(os.path.join(_TF_DIR, filename), encoding="utf-8") as handle:
        return _strip_comments_and_heredocs(handle.read())


_HEREDOC = re.compile(r"<<-?\s*([A-Za-z_]\w*)")


def _strip_comments_and_heredocs(text):
    """Blank out anything that could carry stray braces or misleading CIDRs."""
    lines = []
    terminator = None
    for line in text.splitlines():
        if terminator is not None:
            if line.strip() == terminator:
                terminator = None
            lines.append("")
            continue
        heredoc = _HEREDOC.search(line)
        if heredoc:
            terminator = heredoc.group(1)
            lines.append(_HEREDOC.sub('""', line))
            continue
        lines.append(_strip_line_comment(line))
    return "\n".join(lines)


def _strip_line_comment(line):
    in_string = False
    i = 0
    while i < len(line):
        char = line[i]
        if in_string:
            if char == "\\":
                i += 2
                continue
            if char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "#" or line.startswith("//", i):
            return line[:i]
        i += 1
    return line


def _blocks(text):
    """Yield (header, body) for each `<header> { ... }` at the top level of `text`."""
    index = 0
    while True:
        open_brace = _find_unquoted(text, "{", index)
        if open_brace == -1:
            return
        close_brace = _matching_brace(text, open_brace)
        preceding = [line.strip() for line in text[index:open_brace].splitlines() if line.strip()]
        yield (preceding[-1] if preceding else ""), text[open_brace + 1 : close_brace]
        index = close_brace + 1


def _matching_brace(text, open_index):
    depth = 0
    i = open_index
    in_string = False
    while i < len(text):
        char = text[i]
        if in_string:
            if char == "\\":
                i += 2
                continue
            if char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"unbalanced braces from offset {open_index}")


def _find_unquoted(text, needle, start):
    i = start
    in_string = False
    while i < len(text):
        char = text[i]
        if in_string:
            if char == "\\":
                i += 2
                continue
            if char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == needle:
            return i
        i += 1
    return -1


def _enclosing_object(text, index):
    """Body of the innermost `{ ... }` containing `index`."""
    depth = 0
    for i in range(index, -1, -1):
        if text[i] == "}":
            depth += 1
        elif text[i] == "{":
            if depth == 0:
                return text[i + 1 : _matching_brace(text, i)]
            depth -= 1
    raise ValueError(f"offset {index} is not inside a block")


def _own_attributes(body):
    """Attributes set directly in `body`, ignoring those in nested blocks."""
    flattened = _blank_nested_blocks(body)
    attrs = {}
    for line in flattened.splitlines():
        match = re.match(r"\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*$", line)
        if match:
            attrs[match.group(1)] = match.group(2)
    return attrs


def _blank_nested_blocks(body):
    chars = list(body)
    i = 0
    while i < len(body):
        if body[i] == '"':
            i += 2 if body[i : i + 2] == '\\"' else 1
            while i < len(body) and body[i] != '"':
                i += 2 if body[i] == "\\" else 1
            i += 1
            continue
        if body[i] == "{":
            end = _matching_brace(body, i)
            for j in range(i, end + 1):
                if chars[j] != "\n":
                    chars[j] = " "
            i = end + 1
            continue
        i += 1
    return "".join(chars)


def _quoted_strings(expression):
    return re.findall(r'"([^"]*)"', expression)


def _unquote(value):
    return value.strip().strip('"')


def _as_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
