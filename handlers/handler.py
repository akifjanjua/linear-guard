"""Linear Guard — governed Linear operations for RailCall.

Credentials are resolved exclusively through RailCall's ``vault_get`` helper.
All HTTPS calls use Python ``urllib`` with a certifi-backed SSL context.  The
module never reads credential files, environment variables, or invokes an
external process.
"""

import json
import re
import ssl
from datetime import datetime, timedelta, timezone
import urllib.error
import urllib.request

try:
    import certifi
except ImportError:  # Module still loads; execution gives a clear fix.
    certifi = None


LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
_LINEAR_TOKEN_RE = re.compile(
    r"\b(?:lin_api_|lin_oauth_|pat-)[A-Za-z0-9._-]{8,}\b",
    re.IGNORECASE,
)
_AUTH_HEADER_RE = re.compile(
    r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"
)
_SECRET_FIELD_RE = re.compile(
    r"(?i)(LINEAR_API_KEY\s*[:=]\s*)[^\s,;]+"
)


def _redact(value, *secrets):
    """Return text with Linear credentials and auth headers removed."""
    text = str(value or "")
    for secret in secrets:
        if isinstance(secret, str) and secret:
            text = text.replace(secret, "[REDACTED]")
    text = _LINEAR_TOKEN_RE.sub("[REDACTED]", text)
    text = _AUTH_HEADER_RE.sub(r"\1[REDACTED]", text)
    text = _SECRET_FIELD_RE.sub(r"\1[REDACTED]", text)
    return text


def _build_tls_context():
    """Build a verified SSL context using certifi's Mozilla CA bundle."""
    if certifi is None:
        raise RuntimeError(
            "Linear Guard requires the certifi package for verified HTTPS. "
            "Install it with: python -m pip install certifi"
        )
    return ssl.create_default_context(cafile=certifi.where())


def _extract_api_key(entry):
    """Extract LINEAR_API_KEY from documented RailCall vault shapes."""
    if isinstance(entry, str):
        return entry.strip()
    if not isinstance(entry, dict):
        return ""

    fields = entry.get("fields")
    if isinstance(fields, dict):
        value = fields.get("LINEAR_API_KEY")
        if isinstance(value, str) and value.strip():
            return value.strip()

    value = entry.get("LINEAR_API_KEY")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _load_api_key():
    """Resolve the Linear key only through RailCall's vault abstraction."""
    helpers = globals().get("__rc_helpers__")
    if not isinstance(helpers, dict):
        raise RuntimeError(
            "RailCall did not provide module helpers; the Linear vault "
            "cannot be accessed."
        )

    vault_get = helpers.get("vault_get")
    if not callable(vault_get):
        raise RuntimeError(
            "RailCall's vault_get helper is unavailable. Update RailCall "
            "Station before using Linear Guard."
        )

    try:
        entry = vault_get("linear")
    except Exception as exc:
        raise RuntimeError(
            "RailCall could not read the Linear vault entry."
        ) from None

    api_key = _extract_api_key(entry)
    if not api_key:
        raise RuntimeError(
            "Linear credentials are not configured. Add LINEAR_API_KEY to "
            "the RailCall vault entry for provider 'linear'."
        )
    return api_key


def _network_error_message(exc, api_key):
    reason = getattr(exc, "reason", exc)
    detail = _redact(reason, api_key).strip()
    return detail or type(exc).__name__


def _unknown_write_outcome(detail):
    raise RuntimeError(
        "Linear write outcome is unknown because no confirmed response was "
        "received. Check Linear before retrying this action. "
        f"Transport detail: {detail}"
    ) from None


def _post_graphql(api_key, request_body, *, is_write=False):
    """Send one verified HTTPS request. No command is retried here."""
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
            timeout=25,
            context=_build_tls_context(),
        ) as response:
            return int(response.getcode()), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()
    except (urllib.error.URLError, TimeoutError, OSError, ssl.SSLError) as exc:
        detail = _network_error_message(exc, api_key)
        if is_write:
            _unknown_write_outcome(detail)
        raise RuntimeError(f"Linear network error: {detail}") from None


def _graphql(query, variables=None, *, is_write=False):
    api_key = _load_api_key()
    request_body = json.dumps(
        {"query": query, "variables": variables or {}},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    status, response_bytes = _post_graphql(
        api_key,
        request_body,
        is_write=is_write,
    )

    try:
        response = json.loads(response_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        if is_write and 200 <= status < 300:
            _unknown_write_outcome("Linear returned an unreadable success response.")
        raise RuntimeError(
            f"Linear returned an unreadable response (HTTP {status})."
        ) from exc

    errors = response.get("errors") if isinstance(response, dict) else None

    if status == 429:
        raise RuntimeError(
            "Linear rate limit reached. Wait before trying again."
        )

    if status < 200 or status >= 300:
        message = ""
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            message = _redact(errors[0].get("message") or "", api_key)
        if is_write and status >= 500:
            _unknown_write_outcome(
                f"Linear returned HTTP {status} without confirming the mutation."
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
            message = _redact(
                error.get("message") or "Unknown GraphQL error",
                api_key,
            )
            extensions = error.get("extensions")
            code = ""
            if isinstance(extensions, dict):
                code = _redact(extensions.get("code") or "", api_key)
            messages.append(f"{message} [{code}]" if code else message)
        detail = "; ".join(messages) or "Unknown GraphQL error"
        if is_write:
            raise RuntimeError(
                "Linear did not confirm the write because GraphQL returned "
                f"errors. Check Linear before retrying: {detail}"
            )
        raise RuntimeError("Linear GraphQL error: " + detail)

    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        if is_write:
            _unknown_write_outcome("Linear returned no usable mutation data.")
        raise RuntimeError("Linear returned no usable data.")

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

    team_id = team_id.strip()
    title = title.strip()

    if len(team_id) > 200:
        raise RuntimeError("team_id must be 200 characters or fewer.")
    if len(title) > 255:
        raise RuntimeError("title must be 255 characters or fewer.")

    if description is None:
        description = ""
    if not isinstance(description, str):
        raise RuntimeError(
            "description must be a string."
        )
    if len(description) > 100000:
        raise RuntimeError("description must be 100000 characters or fewer.")

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
                "teamId": team_id,
                "title": title,
                "description": description,
            }
        },
        is_write=True,
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

def linear_update_issue(inputs, stamp):
    """
    Update selected fields on one Linear issue.

    Every invocation is governed by RailCall's approval airlock because the
    manifest declares this command as write_requires_approval.
    """
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

    update_input = {}

    if "title" in inputs:
        title = inputs.get("title")

        if not isinstance(title, str) or not title.strip():
            raise RuntimeError(
                "title must be a non-empty string when supplied."
            )

        title = title.strip()

        if len(title) > 255:
            raise RuntimeError(
                "title must be 255 characters or fewer."
            )

        update_input["title"] = title

    if "description" in inputs:
        description = inputs.get("description")

        if not isinstance(description, str):
            raise RuntimeError(
                "description must be a string when supplied."
            )

        if len(description) > 100000:
            raise RuntimeError(
                "description must be 100000 characters or fewer."
            )

        update_input["description"] = description

    if "state_id" in inputs:
        state_id = inputs.get("state_id")

        if not isinstance(state_id, str) or not state_id.strip():
            raise RuntimeError(
                "state_id must be a non-empty Linear workflow-state UUID."
            )

        state_id = state_id.strip()
        if len(state_id) > 200:
            raise RuntimeError("state_id must be 200 characters or fewer.")
        update_input["stateId"] = state_id

    if "project_id" in inputs:
        project_id = inputs.get("project_id")

        if not isinstance(project_id, str) or not project_id.strip():
            raise RuntimeError(
                "project_id must be a non-empty Linear project UUID."
            )

        project_id = project_id.strip()
        if len(project_id) > 200:
            raise RuntimeError("project_id must be 200 characters or fewer.")
        update_input["projectId"] = project_id

    if "priority" in inputs:
        priority = inputs.get("priority")

        if isinstance(priority, bool):
            raise RuntimeError(
                "priority must be an integer from 0 to 4."
            )

        try:
            priority = int(priority)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "priority must be an integer from 0 to 4."
            ) from exc

        if priority < 0 or priority > 4:
            raise RuntimeError(
                "priority must be between 0 and 4."
            )

        update_input["priority"] = priority

    if not update_input:
        raise RuntimeError(
            "Supply at least one field to update: title, description, "
            "state_id, project_id, or priority."
        )

    status, data = _graphql(
        """
        mutation RailCallUpdateIssue(
          $issueId: String!
          $input: IssueUpdateInput!
        ) {
          issueUpdate(id: $issueId, input: $input) {
            success
            issue {
              id
              identifier
              title
              url
              priority
              updatedAt
              state {
                id
                name
                type
              }
              project {
                id
                name
              }
            }
          }
        }
        """,
        {
            "issueId": issue_id,
            "input": update_input,
        },
        is_write=True,
    )

    payload = data.get("issueUpdate")
    issue = payload.get("issue") if isinstance(payload, dict) else None

    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(issue, dict)
    ):
        raise RuntimeError(
            "Linear did not confirm the issue update."
        )

    state = issue.get("state")
    project = issue.get("project")
    priority = issue.get("priority")

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "issue_id": str(issue.get("id") or ""),
        "identifier": str(issue.get("identifier") or ""),
        "title": str(issue.get("title") or ""),
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
        "updated_at": str(issue.get("updatedAt") or ""),
    }, None


def linear_add_comment(inputs, stamp):
    """
    Add one Markdown comment to a Linear issue.

    The returned body is reduced to a receipt-safe preview; the full comment
    remains in Linear and is never duplicated into the signed receipt.
    """
    issue_id = inputs.get("issue_id")
    body = inputs.get("body")

    if not isinstance(issue_id, str) or not issue_id.strip():
        raise RuntimeError(
            "issue_id must be a non-empty Linear UUID or identifier."
        )

    issue_id = issue_id.strip()

    if len(issue_id) > 200:
        raise RuntimeError(
            "issue_id must be 200 characters or fewer."
        )

    if not isinstance(body, str) or not body.strip():
        raise RuntimeError(
            "body must be a non-empty string."
        )

    body = body.strip()

    if len(body) > 100000:
        raise RuntimeError(
            "body must be 100000 characters or fewer."
        )

    status, data = _graphql(
        """
        mutation RailCallAddComment($input: CommentCreateInput!) {
          commentCreate(input: $input) {
            success
            comment {
              id
              body
              createdAt
            }
          }
        }
        """,
        {
            "input": {
                "issueId": issue_id,
                "body": body,
            }
        },
        is_write=True,
    )

    payload = data.get("commentCreate")
    comment = payload.get("comment") if isinstance(payload, dict) else None

    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(comment, dict)
    ):
        raise RuntimeError(
            "Linear did not confirm comment creation."
        )

    returned_body = comment.get("body")

    if not isinstance(returned_body, str):
        returned_body = ""

    body_preview = returned_body[:200]

    if len(returned_body) > len(body_preview):
        body_preview += "…"

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "comment_id": str(comment.get("id") or ""),
        "issue_id": issue_id,
        "body_preview": body_preview,
        "created_at": str(comment.get("createdAt") or ""),
    }, None


def _bounded_integer(value, name, *, default, minimum, maximum):
    """Coerce one bounded integer without accepting booleans."""
    if value is None:
        value = default
    if isinstance(value, bool):
        raise RuntimeError(
            f"{name} must be an integer between {minimum} and {maximum}."
        )
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"{name} must be an integer between {minimum} and {maximum}."
        ) from exc
    if result < minimum or result > maximum:
        raise RuntimeError(
            f"{name} must be between {minimum} and {maximum}."
        )
    return result


def _parse_linear_datetime(value):
    """Parse a Linear ISO-8601 timestamp, returning None when unavailable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def linear_list_members(inputs, stamp):
    """List up to 100 Linear workspace members for governed assignment flows."""
    status, data = _graphql(
        """
        query RailCallWorkspaceMembers {
          users(first: 100) {
            nodes {
              id
              name
              email
            }
          }
        }
        """
    )

    connection = data.get("users")
    nodes = connection.get("nodes") if isinstance(connection, dict) else None
    if not isinstance(nodes, list):
        raise RuntimeError("Linear did not return a workspace-member list.")

    members = []
    for member in nodes:
        if not isinstance(member, dict):
            continue
        members.append({
            "id": str(member.get("id") or ""),
            "name": str(member.get("name") or "")[:100],
            "email": str(member.get("email") or "")[:200],
        })

    members.sort(key=lambda item: (item["name"].lower(), item["email"].lower()))
    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "member_count": len(members),
        "members_json": json.dumps(
            members,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }, None


def linear_list_cycles(inputs, stamp):
    """List receipt-safe pages of cycles for one Linear team."""
    team_id = inputs.get("team_id")
    if not isinstance(team_id, str) or not team_id.strip():
        raise RuntimeError("team_id must be a non-empty Linear team UUID.")
    team_id = team_id.strip()
    if len(team_id) > 200:
        raise RuntimeError("team_id must be 200 characters or fewer.")

    offset = _bounded_integer(
        inputs.get("offset"),
        "offset",
        default=0,
        minimum=0,
        maximum=1000,
    )
    limit = _bounded_integer(
        inputs.get("limit"),
        "limit",
        default=10,
        minimum=1,
        maximum=25,
    )

    status, data = _graphql(
        """
        query RailCallTeamCycles($teamId: String!) {
          team(id: $teamId) {
            id
            name
            key
            cycles(first: 100) {
              nodes {
                id
                number
                name
                startsAt
                endsAt
                completedAt
              }
            }
          }
        }
        """,
        {"teamId": team_id},
    )

    team = data.get("team")
    if not isinstance(team, dict):
        raise RuntimeError(f"Linear team {team_id!r} was not found.")
    connection = team.get("cycles")
    nodes = connection.get("nodes") if isinstance(connection, dict) else None
    if not isinstance(nodes, list):
        raise RuntimeError("Linear did not return a cycle list for the team.")

    cycles = []
    now = datetime.now(timezone.utc)
    for cycle in nodes:
        if not isinstance(cycle, dict):
            continue
        starts_at = str(cycle.get("startsAt") or "")
        ends_at = str(cycle.get("endsAt") or "")
        completed_at = str(cycle.get("completedAt") or "")
        start_dt = _parse_linear_datetime(starts_at)
        end_dt = _parse_linear_datetime(ends_at)
        if completed_at:
            phase = "completed"
        elif start_dt and end_dt and start_dt <= now <= end_dt:
            phase = "active"
        elif start_dt and start_dt > now:
            phase = "upcoming"
        else:
            phase = "past"
        number = cycle.get("number")
        cycles.append({
            "id": str(cycle.get("id") or ""),
            "number": int(number) if isinstance(number, (int, float)) else 0,
            "name": str(cycle.get("name") or "")[:100],
            "phase": phase,
            "starts_at": starts_at,
            "ends_at": ends_at,
        })

    cycles.sort(
        key=lambda item: (
            _parse_linear_datetime(item["starts_at"])
            or datetime.min.replace(tzinfo=timezone.utc)
        ),
        reverse=True,
    )
    page = cycles[offset:offset + limit]
    next_offset = offset + len(page)
    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "team_id": str(team.get("id") or ""),
        "team_name": str(team.get("name") or ""),
        "team_key": str(team.get("key") or ""),
        "cycle_count": len(cycles),
        "returned_count": len(page),
        "next_offset": next_offset,
        "has_more": next_offset < len(cycles),
        "cycles_json": json.dumps(
            page,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }, None


def linear_sprint_health(inputs, stamp):
    """Summarize the health of one Linear cycle without changing Linear."""
    cycle_id = inputs.get("cycle_id")
    if not isinstance(cycle_id, str) or not cycle_id.strip():
        raise RuntimeError("cycle_id must be a non-empty Linear cycle UUID.")
    cycle_id = cycle_id.strip()
    if len(cycle_id) > 200:
        raise RuntimeError("cycle_id must be 200 characters or fewer.")

    stale_days = _bounded_integer(
        inputs.get("stale_days"),
        "stale_days",
        default=7,
        minimum=1,
        maximum=90,
    )

    status, data = _graphql(
        """
        query RailCallSprintHealth($cycleId: String!) {
          cycle(id: $cycleId) {
            id
            number
            name
            startsAt
            endsAt
            completedAt
            team {
              id
              name
              key
            }
            issues(first: 100) {
              nodes {
                id
                identifier
                title
                priority
                estimate
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
                labels(first: 20) {
                  nodes {
                    id
                    name
                  }
                }
              }
            }
          }
        }
        """,
        {"cycleId": cycle_id},
    )

    cycle = data.get("cycle")
    if not isinstance(cycle, dict):
        raise RuntimeError(f"Linear cycle {cycle_id!r} was not found.")
    team = cycle.get("team")
    connection = cycle.get("issues")
    nodes = connection.get("nodes") if isinstance(connection, dict) else None
    if not isinstance(nodes, list):
        raise RuntimeError("Linear did not return issues for the cycle.")

    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(days=stale_days)
    terminal_types = {"completed", "canceled", "cancelled"}
    counts = {
        "total": 0,
        "backlog": 0,
        "unstarted": 0,
        "started": 0,
        "completed": 0,
        "canceled": 0,
        "unassigned": 0,
        "high_or_urgent": 0,
        "without_estimate": 0,
        "without_labels": 0,
        "stale": 0,
    }
    attention = []

    for issue in nodes:
        if not isinstance(issue, dict):
            continue
        counts["total"] += 1
        state = issue.get("state")
        state_type = (
            str(state.get("type") or "").lower()
            if isinstance(state, dict)
            else ""
        )
        if state_type == "backlog":
            counts["backlog"] += 1
        elif state_type == "unstarted":
            counts["unstarted"] += 1
        elif state_type == "started":
            counts["started"] += 1
        elif state_type == "completed":
            counts["completed"] += 1
        elif state_type in {"canceled", "cancelled"}:
            counts["canceled"] += 1

        assignee = issue.get("assignee")
        labels = issue.get("labels")
        label_nodes = labels.get("nodes") if isinstance(labels, dict) else None
        priority = issue.get("priority")
        estimate = issue.get("estimate")
        updated_at = _parse_linear_datetime(issue.get("updatedAt"))

        reasons = []
        if not isinstance(assignee, dict):
            counts["unassigned"] += 1
            reasons.append("unassigned")
        if isinstance(priority, (int, float)) and int(priority) in {1, 2}:
            counts["high_or_urgent"] += 1
            reasons.append("high_or_urgent")
        if not isinstance(estimate, (int, float)) or float(estimate) <= 0:
            counts["without_estimate"] += 1
            reasons.append("no_estimate")
        if not isinstance(label_nodes, list) or not label_nodes:
            counts["without_labels"] += 1
            reasons.append("no_labels")
        if (
            state_type not in terminal_types
            and updated_at is not None
            and updated_at < stale_before
        ):
            counts["stale"] += 1
            reasons.append("stale")

        if reasons and len(attention) < 15:
            attention.append({
                "identifier": str(issue.get("identifier") or ""),
                "title": str(issue.get("title") or "")[:100],
                "state": (
                    str(state.get("name") or "")
                    if isinstance(state, dict)
                    else ""
                ),
                "reasons": reasons,
            })

    non_canceled = max(0, counts["total"] - counts["canceled"])
    completion_percent = (
        round((counts["completed"] / non_canceled) * 100, 1)
        if non_canceled
        else 0.0
    )
    warnings = []
    if counts["unassigned"]:
        warnings.append(f"{counts['unassigned']} issue(s) are unassigned")
    if counts["high_or_urgent"]:
        warnings.append(
            f"{counts['high_or_urgent']} issue(s) are high or urgent priority"
        )
    if counts["stale"]:
        warnings.append(
            f"{counts['stale']} open issue(s) have not changed in {stale_days}+ days"
        )
    if counts["without_estimate"]:
        warnings.append(f"{counts['without_estimate']} issue(s) have no estimate")
    if counts["without_labels"]:
        warnings.append(f"{counts['without_labels']} issue(s) have no labels")

    cycle_number = (
        int(cycle.get("number"))
        if isinstance(cycle.get("number"), (int, float))
        else 0
    )
    cycle_name = str(cycle.get("name") or "").strip()
    if not cycle_name:
        cycle_name = f"Cycle {cycle_number}" if cycle_number else "Unnamed cycle"

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "cycle_id": str(cycle.get("id") or ""),
        "cycle_number": cycle_number,
        "cycle_name": cycle_name,
        "team_id": str(team.get("id") or "") if isinstance(team, dict) else "",
        "team_name": (
            str(team.get("name") or "") if isinstance(team, dict) else ""
        ),
        "total_issues": counts["total"],
        "completed_issues": counts["completed"],
        "completion_percent": completion_percent,
        "unassigned_issues": counts["unassigned"],
        "high_or_urgent_issues": counts["high_or_urgent"],
        "without_estimate": counts["without_estimate"],
        "without_labels": counts["without_labels"],
        "stale_issues": counts["stale"],
        "result_cap_reached": counts["total"] >= 100,
        "state_counts_json": json.dumps(
            {
                key: counts[key]
                for key in (
                    "backlog",
                    "unstarted",
                    "started",
                    "completed",
                    "canceled",
                )
            },
            separators=(",", ":"),
        ),
        "warnings_json": json.dumps(
            warnings,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "attention_issues_json": json.dumps(
            attention,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }, None

