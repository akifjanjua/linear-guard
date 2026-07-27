"""
Linear Guard for RailCall.

Governed Linear module:
- linear.get_current_user
- linear.list_teams
- linear.list_projects
- linear.list_labels
- linear.list_workflow_states
- linear.search_issues
- linear.get_issue
- linear.create_issue

The Linear API key is loaded from the RailCall vault entry named "linear".
No credential is stored in this source file or returned in receipts.
"""

import json
import shutil
import subprocess
import ssl
import urllib.error
import urllib.request
from pathlib import Path



LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
def _build_tls_context():
    """
    Build a verified HTTPS context using Python defaults plus the
    native Windows ROOT and CA certificate stores.

    This keeps hostname and certificate verification enabled and
    requires no third-party Python package.
    """
    context = ssl.create_default_context()

    enum_certificates = getattr(
        ssl,
        "enum_certificates",
        None,
    )

    if enum_certificates is None:
        return context

    pem_certificates = []

    for store_name in ("ROOT", "CA"):
        try:
            certificates = enum_certificates(store_name)
        except OSError:
            continue

        for cert_bytes, encoding_type, trust in certificates:
            if encoding_type != "x509_asn":
                continue

            try:
                pem_certificates.append(
                    ssl.DER_cert_to_PEM_cert(cert_bytes)
                )
            except (ValueError, ssl.SSLError):
                continue

    if pem_certificates:
        context.load_verify_locations(
            cadata="\n".join(pem_certificates)
        )

    return context


TLS_CONTEXT = _build_tls_context()


def _extract_api_key(entry):
    """Extract a Linear key from supported RailCall credential shapes."""
    if isinstance(entry, str):
        return entry.strip()

    if not isinstance(entry, dict):
        return ""

    fields = entry.get("fields")

    if isinstance(fields, dict):
        for field_name in (
            "LINEAR_API_KEY",
            "api_key",
            "token",
        ):
            value = fields.get(field_name)
            if isinstance(value, str) and value.strip():
                return value.strip()

    for field_name in (
        "LINEAR_API_KEY",
        "api_key",
        "token",
    ):
        value = entry.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def _load_api_key():
    """
    Load the Linear key without placing it in source code or command inputs.

    First supports RailCall's legacy provider vault helper. Then supports
    station-v0.27's named integration credential store.
    """
    helpers = __rc_helpers__  # injected by RailCall
    vault_get = helpers.get("vault_get")

    if callable(vault_get):
        legacy_key = _extract_api_key(vault_get("linear"))

        if legacy_key:
            return legacy_key

    credential_file = (
        Path.home()
        / ".railcall"
        / "station"
        / ".railcall_workspace"
        / "credentials.local.json"
    )

    try:
        credential_store = json.loads(
            credential_file.read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "No RailCall integration credential store was found."
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "RailCall's integration credential store could not be read."
        ) from exc

    provider = credential_store.get("linear")

    if not isinstance(provider, dict):
        raise RuntimeError(
            "No Linear integration credential is configured."
        )

    credentials = provider.get("credentials")

    if not isinstance(credentials, dict):
        raise RuntimeError(
            "The Linear integration has no saved credentials."
        )

    default_id = provider.get("default")
    candidates = []

    if isinstance(default_id, str):
        default_credential = credentials.get(default_id)

        if isinstance(default_credential, dict):
            candidates.append(default_credential)

    for credential_id, credential in credentials.items():
        if (
            credential_id != default_id
            and isinstance(credential, dict)
        ):
            candidates.append(credential)

    for credential in candidates:
        api_key = _extract_api_key(credential)

        if api_key:
            return api_key

    raise RuntimeError(
        "The configured Linear credential is missing LINEAR_API_KEY."
    )


def _curl_config_quote(value):
    """
    Escape text for curl config-file syntax.

    The Linear API key is supplied through curl's standard input rather
    than as a command-line argument.
    """
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def _post_graphql_with_curl(api_key, request_body):
    """
    Perform a verified HTTPS request using the system curl executable.

    curl continues to verify the server certificate and hostname.
    """
    curl_path = shutil.which("curl")

    if not curl_path:
        raise RuntimeError(
            "Python TLS verification failed and curl is unavailable."
        )

    body_text = request_body.decode("utf-8")

    config = "\n".join([
        "silent",
        "show-error",
        'request = "POST"',
        'url = "https://api.linear.app/graphql"',
        'header = "Content-Type: application/json"',
        (
            'header = "Authorization: '
            + _curl_config_quote(api_key)
            + '"'
        ),
        (
            'data = "'
            + _curl_config_quote(body_text)
            + '"'
        ),
        "connect-timeout = 10",
        "max-time = 25",
        (
            'write-out = '
            '"\\n__RAILCALL_HTTP_STATUS__:%{http_code}"'
        ),
    ]) + "\n"

    try:
        completed = subprocess.run(
            [curl_path, "--config", "-"],
            input=config.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )

    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Linear request timed out while using curl."
        ) from exc

    except OSError as exc:
        raise RuntimeError(
            f"Could not start curl: {exc}"
        ) from exc

    if completed.returncode != 0:
        error_text = completed.stderr.decode(
            "utf-8",
            errors="replace",
        ).strip()

        raise RuntimeError(
            "Linear curl transport failed"
            + (f": {error_text}" if error_text else ".")
        )

    marker = b"\n__RAILCALL_HTTP_STATUS__:"
    response_body, separator, status_bytes = (
        completed.stdout.rpartition(marker)
    )

    if not separator:
        raise RuntimeError(
            "curl returned no HTTP status marker."
        )

    try:
        status = int(status_bytes.strip())
    except ValueError as exc:
        raise RuntimeError(
            "curl returned an invalid HTTP status."
        ) from exc

    return status, response_body.rstrip(b"\r\n")


def _post_graphql(api_key, request_body):
    """
    Try Python's verified TLS connection first.

    On a Windows certificate-chain verification failure, retry through
    system curl with certificate verification still enabled.
    """
    request = urllib.request.Request(
        LINEAR_GRAPHQL_URL,
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
            context=TLS_CONTEXT,
        ) as response:
            return int(response.getcode()), response.read()

    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()

    except urllib.error.URLError as exc:
        reason_text = str(exc.reason)

        certificate_failure = (
            isinstance(
                exc.reason,
                ssl.SSLCertVerificationError,
            )
            or "CERTIFICATE_VERIFY_FAILED" in reason_text
            or "certificate has expired" in reason_text.lower()
        )

        if certificate_failure:
            return _post_graphql_with_curl(
                api_key,
                request_body,
            )

        raise RuntimeError(
            f"Linear network error: {exc.reason}"
        ) from exc


def _graphql(query, variables=None):
    api_key = _load_api_key()

    request_body = json.dumps(
        {
            "query": query,
            "variables": variables or {},
        }
    ).encode("utf-8")

    status, response_bytes = _post_graphql(
        api_key,
        request_body,
    )

    try:
        response = json.loads(
            response_bytes.decode("utf-8")
        )
    except Exception as exc:
        raise RuntimeError(
            f"Linear returned an unreadable response "
            f"(HTTP {status})."
        ) from exc

    errors = response.get("errors")

    if status == 429:
        raise RuntimeError(
            "Linear rate limit reached. Wait before trying again."
        )

    if status < 200 or status >= 300:
        message = ""

        if isinstance(errors, list) and errors:
            first_error = errors[0]

            if isinstance(first_error, dict):
                message = str(
                    first_error.get("message") or ""
                )

        raise RuntimeError(
            f"Linear API request failed with HTTP {status}"
            + (f": {message}" if message else ".")
        )

    if isinstance(errors, list) and errors:
        messages = []

        for error in errors[:3]:
            if not isinstance(error, dict):
                continue

            message = str(
                error.get("message")
                or "Unknown GraphQL error"
            )

            extensions = error.get("extensions")
            code = ""

            if isinstance(extensions, dict):
                code = str(
                    extensions.get("code") or ""
                )

            messages.append(
                f"{message} [{code}]"
                if code
                else message
            )

        raise RuntimeError(
            "Linear GraphQL error: "
            + "; ".join(messages)
        )

    data = response.get("data")

    if not isinstance(data, dict):
        raise RuntimeError(
            "Linear returned no usable data."
        )

    return status, data


def linear_get_current_user(inputs, stamp):
    status, data = _graphql(
        """
        query RailCallCurrentUser {
          viewer {
            id
            name
            email
          }
        }
        """
    )

    viewer = data.get("viewer")
    if not isinstance(viewer, dict):
        raise RuntimeError(
            "Linear did not return the authenticated user."
        )

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "user_id": str(viewer.get("id") or ""),
        "name": str(viewer.get("name") or ""),
        "email": str(viewer.get("email") or ""),
    }, None


def linear_list_teams(inputs, stamp):
    status, data = _graphql(
        """
        query RailCallTeams {
          teams(first: 50) {
            nodes {
              id
              name
              key
            }
          }
        }
        """
    )

    connection = data.get("teams")
    nodes = connection.get("nodes") if isinstance(connection, dict) else None

    if not isinstance(nodes, list):
        raise RuntimeError(
            "Linear did not return a team list."
        )

    teams = []
    for team in nodes:
        if not isinstance(team, dict):
            continue
        teams.append({
            "id": str(team.get("id") or ""),
            "name": str(team.get("name") or ""),
            "key": str(team.get("key") or ""),
        })

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "team_count": len(teams),
        "teams_json": json.dumps(
            teams,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }, None



def linear_list_projects(inputs, stamp):
    """List up to 100 projects visible to the configured Linear account."""
    status, data = _graphql(
        """
        query RailCallProjects {
          projects(first: 100) {
            nodes {
              id
              name
            }
          }
        }
        """
    )

    connection = data.get("projects")
    nodes = connection.get("nodes") if isinstance(connection, dict) else None

    if not isinstance(nodes, list):
        raise RuntimeError(
            "Linear did not return a project list."
        )

    projects = []

    for project in nodes:
        if not isinstance(project, dict):
            continue

        projects.append({
            "id": str(project.get("id") or ""),
            "name": str(project.get("name") or ""),
        })

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "project_count": len(projects),
        "projects_json": json.dumps(
            projects,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }, None


def linear_list_labels(inputs, stamp):
    """List up to 100 issue labels visible to the configured account."""
    status, data = _graphql(
        """
        query RailCallIssueLabels {
          issueLabels(first: 100) {
            nodes {
              id
              name
            }
          }
        }
        """
    )

    connection = data.get("issueLabels")
    nodes = connection.get("nodes") if isinstance(connection, dict) else None

    if not isinstance(nodes, list):
        raise RuntimeError(
            "Linear did not return an issue-label list."
        )

    labels = []

    for label in nodes:
        if not isinstance(label, dict):
            continue

        labels.append({
            "id": str(label.get("id") or ""),
            "name": str(label.get("name") or ""),
        })

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "label_count": len(labels),
        "labels_json": json.dumps(
            labels,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }, None


def linear_list_workflow_states(inputs, stamp):
    """
    List Linear workflow states in receipt-safe pages.

    RailCall Studio currently truncates long string fields in receipt views,
    so this command keeps each JSON page below a conservative character limit.
    """
    offset = inputs.get("offset", 0)
    limit = inputs.get("limit", 10)

    try:
        offset = int(offset)
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "offset and limit must be integers."
        ) from exc

    if offset < 0:
        raise RuntimeError(
            "offset must be zero or greater."
        )

    if limit < 1 or limit > 25:
        raise RuntimeError(
            "limit must be between 1 and 25."
        )

    status, data = _graphql(
        """
        query RailCallWorkflowStates {
          workflowStates(first: 100) {
            nodes {
              id
              name
              type
              position
            }
          }
        }
        """
    )

    connection = data.get("workflowStates")
    nodes = connection.get("nodes") if isinstance(connection, dict) else None

    if not isinstance(nodes, list):
        raise RuntimeError(
            "Linear did not return a workflow-state list."
        )

    states = []

    for state in nodes:
        if not isinstance(state, dict):
            continue

        position = state.get("position")

        states.append({
            "id": str(state.get("id") or ""),
            "name": str(state.get("name") or "")[:80],
            "type": str(state.get("type") or ""),
            "position": position if isinstance(position, (int, float)) else None,
        })

    states.sort(
        key=lambda item: (
            item["position"] is None,
            item["position"] if item["position"] is not None else 0,
            item["name"].lower(),
        )
    )

    requested_page = states[offset:offset + limit]
    page = []
    max_json_characters = 260

    for state in requested_page:
        candidate = page + [state]
        candidate_json = json.dumps(
            candidate,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        if page and len(candidate_json) > max_json_characters:
            break

        page = candidate

    page_json = json.dumps(
        page,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    returned_count = len(page)
    next_offset = offset + returned_count
    has_more = next_offset < len(states)

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "state_count": len(states),
        "returned_count": returned_count,
        "next_offset": next_offset,
        "has_more": has_more,
        "workflow_states_json": page_json,
    }, None



def linear_search_issues(inputs, stamp):
    """
    Search issue titles and descriptions, returning receipt-safe pages.

    The command searches up to 100 of the most recently updated matches.
    Use offset to retrieve additional receipt-safe pages from that result set.
    """
    query_text = inputs.get("query")
    offset = inputs.get("offset", 0)
    limit = inputs.get("limit", 10)

    if not isinstance(query_text, str) or not query_text.strip():
        raise RuntimeError(
            "query must be a non-empty string."
        )

    query_text = query_text.strip()

    if len(query_text) > 200:
        raise RuntimeError(
            "query must be 200 characters or fewer."
        )

    try:
        offset = int(offset)
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "offset and limit must be integers."
        ) from exc

    if offset < 0:
        raise RuntimeError(
            "offset must be zero or greater."
        )

    if limit < 1 or limit > 25:
        raise RuntimeError(
            "limit must be between 1 and 25."
        )

    status, data = _graphql(
        """
        query RailCallSearchIssues($query: String!) {
          issues(
            first: 100
            orderBy: updatedAt
            filter: {
              or: [
                { title: { containsIgnoreCase: $query } }
                { description: { containsIgnoreCase: $query } }
              ]
            }
          ) {
            nodes {
              identifier
              title
              priority
              updatedAt
              state {
                name
              }
            }
          }
        }
        """,
        {
            "query": query_text,
        },
    )

    connection = data.get("issues")
    nodes = connection.get("nodes") if isinstance(connection, dict) else None

    if not isinstance(nodes, list):
        raise RuntimeError(
            "Linear did not return an issue search result."
        )

    issues = []

    for issue in nodes:
        if not isinstance(issue, dict):
            continue

        state = issue.get("state")
        priority = issue.get("priority")

        issues.append({
            "identifier": str(issue.get("identifier") or ""),
            "title": str(issue.get("title") or "")[:100],
            "state": (
                str(state.get("name") or "")
                if isinstance(state, dict)
                else ""
            ),
            "priority": (
                int(priority)
                if isinstance(priority, (int, float))
                else 0
            ),
            "updated_at": str(issue.get("updatedAt") or ""),
        })

    requested_page = issues[offset:offset + limit]
    page = []
    max_json_characters = 260

    for issue in requested_page:
        candidate = page + [issue]
        candidate_json = json.dumps(
            candidate,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        if page and len(candidate_json) > max_json_characters:
            break

        page = candidate

    page_json = json.dumps(
        page,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    returned_count = len(page)
    next_offset = offset + returned_count
    has_more = next_offset < len(issues)

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "matched_count": len(issues),
        "returned_count": returned_count,
        "next_offset": next_offset,
        "has_more": has_more,
        "result_cap_reached": len(issues) >= 100,
        "issues_json": page_json,
    }, None


def linear_get_issue(inputs, stamp):
    """Fetch one Linear issue by UUID or shorthand identifier such as RAI-9."""
    issue_id = inputs.get("issue_id")

    if not isinstance(issue_id, str) or not issue_id.strip():
        raise RuntimeError(
            "issue_id must be a non-empty Linear UUID or identifier."
        )

    issue_id = issue_id.strip()

    if len(issue_id) > 200:
        raise RuntimeError(
            "issue_id must be 200 characters or fewer."
        )

    status, data = _graphql(
        """
        query RailCallGetIssue($issueId: String!) {
          issue(id: $issueId) {
            id
            identifier
            title
            description
            url
            priority
            createdAt
            updatedAt
            state {
              id
              name
              type
            }
            assignee {
              id
              name
            }
            project {
              id
              name
            }
            team {
              id
              name
              key
            }
          }
        }
        """,
        {
            "issueId": issue_id,
        },
    )

    issue = data.get("issue")

    if not isinstance(issue, dict):
        raise RuntimeError(
            f"Linear issue {issue_id!r} was not found."
        )

    state = issue.get("state")
    assignee = issue.get("assignee")
    project = issue.get("project")
    team = issue.get("team")
    description = issue.get("description")
    priority = issue.get("priority")

    if not isinstance(description, str):
        description = ""

    description_preview = description[:240]

    if len(description) > len(description_preview):
        description_preview += "…"

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "issue_id": str(issue.get("id") or ""),
        "identifier": str(issue.get("identifier") or ""),
        "title": str(issue.get("title") or ""),
        "description_preview": description_preview,
        "url": str(issue.get("url") or ""),
        "priority": (
            int(priority)
            if isinstance(priority, (int, float))
            else 0
        ),
        "state_id": (
            str(state.get("id") or "")
            if isinstance(state, dict)
            else ""
        ),
        "state_name": (
            str(state.get("name") or "")
            if isinstance(state, dict)
            else ""
        ),
        "state_type": (
            str(state.get("type") or "")
            if isinstance(state, dict)
            else ""
        ),
        "assignee_id": (
            str(assignee.get("id") or "")
            if isinstance(assignee, dict)
            else ""
        ),
        "assignee_name": (
            str(assignee.get("name") or "")
            if isinstance(assignee, dict)
            else ""
        ),
        "project_id": (
            str(project.get("id") or "")
            if isinstance(project, dict)
            else ""
        ),
        "project_name": (
            str(project.get("name") or "")
            if isinstance(project, dict)
            else ""
        ),
        "team_id": (
            str(team.get("id") or "")
            if isinstance(team, dict)
            else ""
        ),
        "team_name": (
            str(team.get("name") or "")
            if isinstance(team, dict)
            else ""
        ),
        "team_key": (
            str(team.get("key") or "")
            if isinstance(team, dict)
            else ""
        ),
        "created_at": str(issue.get("createdAt") or ""),
        "updated_at": str(issue.get("updatedAt") or ""),
    }, None


def linear_create_issue(inputs, stamp):
    team_id = inputs.get("team_id")
    title = inputs.get("title")
    description = inputs.get("description")

    if not isinstance(team_id, str) or not team_id.strip():
        raise RuntimeError(
            "team_id must be a non-empty Linear team UUID."
        )

    if not isinstance(title, str) or not title.strip():
        raise RuntimeError(
            "title must be a non-empty string."
        )

    if description is None:
        description = ""
    if not isinstance(description, str):
        raise RuntimeError(
            "description must be a string."
        )

    status, data = _graphql(
        """
        mutation RailCallCreateIssue($input: IssueCreateInput!) {
          issueCreate(input: $input) {
            success
            issue {
              id
              identifier
              title
              url
            }
          }
        }
        """,
        {
            "input": {
                "teamId": team_id.strip(),
                "title": title.strip(),
                "description": description,
            }
        },
    )

    payload = data.get("issueCreate")
    issue = payload.get("issue") if isinstance(payload, dict) else None

    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(issue, dict)
    ):
        raise RuntimeError(
            "Linear did not confirm issue creation."
        )

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "issue_id": str(issue.get("id") or ""),
        "identifier": str(issue.get("identifier") or ""),
        "title": str(issue.get("title") or ""),
        "url": str(issue.get("url") or ""),
    }, None
