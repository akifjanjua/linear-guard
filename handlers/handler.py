"""Linear Guard — governed Linear operations for RailCall.

Credentials are resolved exclusively through RailCall's ``vault_get`` helper.
All HTTPS calls use Python ``urllib`` with a certifi-backed SSL context.  The
module never reads credential files, environment variables, or invokes an
external process.
"""

import json
import re
import ssl
import uuid
from datetime import datetime, timedelta, timezone
import urllib.error
import urllib.request

try:
    import certifi
except ImportError:  # Module still loads; execution gives a clear fix.
    certifi = None


LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
# No \b word-boundary anchors: a token glued directly to adjacent word
# characters (e.g. concatenated into an error string with no delimiter)
# still needs to be caught by pattern-based redaction, not just tokens with
# clean boundaries on both sides.
_LINEAR_TOKEN_RE = re.compile(
    r"(?:lin_api_|lin_oauth_|pat-)[A-Za-z0-9._-]{8,}",
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
            return int(response.getcode()), response.read(), response.headers
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(), exc.headers
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

    status, response_bytes, response_headers = _post_graphql(
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
        retry_after = response_headers.get("Retry-After") if response_headers else None
        if isinstance(retry_after, str) and retry_after.strip():
            raise RuntimeError(
                f"Linear rate limit reached. Linear says to wait {retry_after.strip()} "
                "seconds before trying again."
            )
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
    parent_id = inputs.get("parent_id")

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

    create_input = {
        "teamId": team_id,
        "title": title,
        "description": description,
    }

    if parent_id is not None:
        if not isinstance(parent_id, str) or not parent_id.strip():
            raise RuntimeError(
                "parent_id must be a non-empty Linear issue UUID or identifier when supplied."
            )
        parent_id = parent_id.strip()
        if len(parent_id) > 200:
            raise RuntimeError("parent_id must be 200 characters or fewer.")
        create_input["parentId"] = parent_id

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
        {"input": create_input},
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

    parent_id = inputs.get("parent_id")
    clear_parent = _optional_boolean(inputs, "clear_parent")

    if parent_id is not None and clear_parent:
        raise RuntimeError(
            "Supply parent_id or clear_parent=true, not both."
        )

    if clear_parent:
        update_input["parentId"] = None
    elif "parent_id" in inputs:
        if not isinstance(parent_id, str) or not parent_id.strip():
            raise RuntimeError(
                "parent_id must be a non-empty Linear issue UUID or identifier when supplied."
            )
        parent_id = parent_id.strip()
        if len(parent_id) > 200:
            raise RuntimeError("parent_id must be 200 characters or fewer.")
        update_input["parentId"] = parent_id

    if not update_input:
        raise RuntimeError(
            "Supply at least one field to update: title, description, "
            "state_id, project_id, priority, parent_id, or clear_parent."
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
              parent {
                id
                identifier
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
    parent = issue.get("parent")
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
        "parent_id": (
            str(parent.get("id") or "")
            if isinstance(parent, dict)
            else ""
        ),
        "parent_identifier": (
            str(parent.get("identifier") or "")
            if isinstance(parent, dict)
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


def linear_create_label(inputs, stamp):
    """Create a Linear issue label, optionally scoped to one team."""
    name = inputs.get("name")
    team_id = inputs.get("team_id")
    color = inputs.get("color")
    description = inputs.get("description")

    if not isinstance(name, str) or not name.strip():
        raise RuntimeError(
            "name must be a non-empty string."
        )

    name = name.strip()

    if len(name) > 255:
        raise RuntimeError("name must be 255 characters or fewer.")

    label_input = {"name": name}

    if team_id is not None:
        if not isinstance(team_id, str) or not team_id.strip():
            raise RuntimeError(
                "team_id must be a non-empty Linear team UUID when supplied."
            )
        team_id = team_id.strip()
        if len(team_id) > 200:
            raise RuntimeError("team_id must be 200 characters or fewer.")
        label_input["teamId"] = team_id

    if color is not None:
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color.strip()):
            raise RuntimeError(
                "color must be a hex color like #4EA7FC when supplied."
            )
        label_input["color"] = color.strip()

    if description is not None:
        if not isinstance(description, str):
            raise RuntimeError(
                "description must be a string when supplied."
            )
        if len(description) > 2000:
            raise RuntimeError("description must be 2000 characters or fewer.")
        label_input["description"] = description

    status, data = _graphql(
        """
        mutation RailCallCreateLabel($input: IssueLabelCreateInput!) {
          issueLabelCreate(input: $input) {
            success
            issueLabel {
              id
              name
              color
              description
              isGroup
              team {
                id
                name
              }
            }
          }
        }
        """,
        {"input": label_input},
        is_write=True,
    )

    payload = data.get("issueLabelCreate")
    label = payload.get("issueLabel") if isinstance(payload, dict) else None

    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(label, dict)
    ):
        raise RuntimeError(
            "Linear did not confirm label creation."
        )

    team = label.get("team")

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "label_id": str(label.get("id") or ""),
        "name": str(label.get("name") or ""),
        "color": str(label.get("color") or ""),
        "description": str(label.get("description") or ""),
        "is_group": bool(label.get("isGroup")),
        "team_id": str(team.get("id") or "") if isinstance(team, dict) else "",
        "team_name": str(team.get("name") or "") if isinstance(team, dict) else "",
    }, None


def linear_archive_label(inputs, stamp):
    """
    Archive a Linear issue label.

    Linear's API names this operation "retire" (issueLabelRetire), not
    "archive" -- there is no issueLabelArchive mutation. Retiring hides the
    label from pickers while preserving every existing issue association and
    all history; it can be brought back through Linear's own UI or the
    issueLabelRestore mutation, which this module does not expose. The
    command is named archive_label to match RailCall's convention for this
    kind of governed soft-removal.
    """
    label_id = inputs.get("label_id")

    if not isinstance(label_id, str) or not label_id.strip():
        raise RuntimeError(
            "label_id must be a non-empty Linear label UUID."
        )

    label_id = label_id.strip()

    if len(label_id) > 200:
        raise RuntimeError("label_id must be 200 characters or fewer.")

    status, data = _graphql(
        """
        mutation RailCallArchiveLabel($labelId: String!) {
          issueLabelRetire(id: $labelId) {
            success
            issueLabel {
              id
              name
              retiredAt
            }
          }
        }
        """,
        {"labelId": label_id},
        is_write=True,
    )

    payload = data.get("issueLabelRetire")
    label = payload.get("issueLabel") if isinstance(payload, dict) else None

    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(label, dict)
    ):
        raise RuntimeError(
            "Linear did not confirm the label archive."
        )

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "label_id": str(label.get("id") or ""),
        "name": str(label.get("name") or ""),
        "retired_at": str(label.get("retiredAt") or ""),
    }, None


def linear_archive_issue(inputs, stamp):
    """
    Archive a Linear issue, optionally moving it to trash.

    Linear's issueArchive mutation returns only {success, lastSyncId} -- no
    updated issue entity -- so this command echoes the requested issue_id
    rather than returning fields Linear's API does not provide here.
    """
    issue_id = inputs.get("issue_id")
    trash = inputs.get("trash", False)

    if not isinstance(issue_id, str) or not issue_id.strip():
        raise RuntimeError(
            "issue_id must be a non-empty Linear UUID or identifier."
        )

    issue_id = issue_id.strip()

    if len(issue_id) > 200:
        raise RuntimeError("issue_id must be 200 characters or fewer.")

    if not isinstance(trash, bool):
        raise RuntimeError(
            "trash must be a boolean when supplied."
        )

    status, data = _graphql(
        """
        mutation RailCallArchiveIssue($issueId: String!, $trash: Boolean) {
          issueArchive(id: $issueId, trash: $trash) {
            success
          }
        }
        """,
        {"issueId": issue_id, "trash": trash},
        is_write=True,
    )

    payload = data.get("issueArchive")

    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise RuntimeError(
            "Linear did not confirm the issue archive."
        )

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "issue_id": issue_id,
        "archived": True,
        "trashed": trash,
    }, None


def linear_update_comment(inputs, stamp):
    """Update the body of an existing Linear comment."""
    comment_id = inputs.get("comment_id")
    body = inputs.get("body")

    if not isinstance(comment_id, str) or not comment_id.strip():
        raise RuntimeError(
            "comment_id must be a non-empty Linear comment UUID."
        )

    comment_id = comment_id.strip()

    if len(comment_id) > 200:
        raise RuntimeError("comment_id must be 200 characters or fewer.")

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
        mutation RailCallUpdateComment(
          $commentId: String!
          $input: CommentUpdateInput!
        ) {
          commentUpdate(id: $commentId, input: $input) {
            success
            comment {
              id
              body
              updatedAt
              editedAt
            }
          }
        }
        """,
        {"commentId": comment_id, "input": {"body": body}},
        is_write=True,
    )

    payload = data.get("commentUpdate")
    comment = payload.get("comment") if isinstance(payload, dict) else None

    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(comment, dict)
    ):
        raise RuntimeError(
            "Linear did not confirm the comment update."
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
        "body_preview": body_preview,
        "updated_at": str(comment.get("updatedAt") or ""),
        "edited_at": str(comment.get("editedAt") or ""),
    }, None


def linear_create_attachment(inputs, stamp):
    """Attach an external URL to a Linear issue."""
    issue_id = inputs.get("issue_id")
    title = inputs.get("title")
    url = inputs.get("url")
    subtitle = inputs.get("subtitle")

    if not isinstance(issue_id, str) or not issue_id.strip():
        raise RuntimeError(
            "issue_id must be a non-empty Linear UUID or identifier."
        )

    issue_id = issue_id.strip()

    if len(issue_id) > 200:
        raise RuntimeError("issue_id must be 200 characters or fewer.")

    if not isinstance(title, str) or not title.strip():
        raise RuntimeError(
            "title must be a non-empty string."
        )

    title = title.strip()

    if len(title) > 255:
        raise RuntimeError("title must be 255 characters or fewer.")

    if not isinstance(url, str) or not url.strip():
        raise RuntimeError(
            "url must be a non-empty string."
        )

    url = url.strip()

    if len(url) > 2000:
        raise RuntimeError("url must be 2000 characters or fewer.")

    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise RuntimeError("url must start with http:// or https://.")

    attachment_input = {
        "issueId": issue_id,
        "title": title,
        "url": url,
    }

    if subtitle is not None:
        if not isinstance(subtitle, str):
            raise RuntimeError(
                "subtitle must be a string when supplied."
            )
        if len(subtitle) > 255:
            raise RuntimeError("subtitle must be 255 characters or fewer.")
        attachment_input["subtitle"] = subtitle

    status, data = _graphql(
        """
        mutation RailCallCreateAttachment($input: AttachmentCreateInput!) {
          attachmentCreate(input: $input) {
            success
            attachment {
              id
              title
              subtitle
              url
              createdAt
              issue {
                id
                identifier
              }
            }
          }
        }
        """,
        {"input": attachment_input},
        is_write=True,
    )

    payload = data.get("attachmentCreate")
    attachment = payload.get("attachment") if isinstance(payload, dict) else None

    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(attachment, dict)
    ):
        raise RuntimeError(
            "Linear did not confirm attachment creation."
        )

    linked_issue = attachment.get("issue")

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "attachment_id": str(attachment.get("id") or ""),
        "title": str(attachment.get("title") or ""),
        "subtitle": str(attachment.get("subtitle") or ""),
        "url": str(attachment.get("url") or ""),
        "created_at": str(attachment.get("createdAt") or ""),
        "issue_id": (
            str(linked_issue.get("id") or "")
            if isinstance(linked_issue, dict)
            else ""
        ),
        "issue_identifier": (
            str(linked_issue.get("identifier") or "")
            if isinstance(linked_issue, dict)
            else ""
        ),
    }, None


_ISSUE_RELATION_TYPES = {"blocks", "duplicate", "related", "similar"}


def linear_link_issues(inputs, stamp):
    """Create a typed relation (blocks, duplicate, related, or similar) between two Linear issues."""
    issue_id = inputs.get("issue_id")
    related_issue_id = inputs.get("related_issue_id")
    relation_type = inputs.get("type")

    if not isinstance(issue_id, str) or not issue_id.strip():
        raise RuntimeError(
            "issue_id must be a non-empty Linear UUID or identifier."
        )

    issue_id = issue_id.strip()

    if len(issue_id) > 200:
        raise RuntimeError("issue_id must be 200 characters or fewer.")

    if not isinstance(related_issue_id, str) or not related_issue_id.strip():
        raise RuntimeError(
            "related_issue_id must be a non-empty Linear UUID or identifier."
        )

    related_issue_id = related_issue_id.strip()

    if len(related_issue_id) > 200:
        raise RuntimeError("related_issue_id must be 200 characters or fewer.")

    if issue_id == related_issue_id:
        raise RuntimeError(
            "issue_id and related_issue_id must refer to different issues."
        )

    if not isinstance(relation_type, str) or relation_type.strip() not in _ISSUE_RELATION_TYPES:
        raise RuntimeError(
            "type must be one of: " + ", ".join(sorted(_ISSUE_RELATION_TYPES)) + "."
        )

    relation_type = relation_type.strip()

    status, data = _graphql(
        """
        mutation RailCallLinkIssues($input: IssueRelationCreateInput!) {
          issueRelationCreate(input: $input) {
            success
            issueRelation {
              id
              type
              createdAt
              issue {
                id
                identifier
              }
              relatedIssue {
                id
                identifier
              }
            }
          }
        }
        """,
        {
            "input": {
                "issueId": issue_id,
                "relatedIssueId": related_issue_id,
                "type": relation_type,
            }
        },
        is_write=True,
    )

    payload = data.get("issueRelationCreate")
    relation = payload.get("issueRelation") if isinstance(payload, dict) else None

    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(relation, dict)
    ):
        raise RuntimeError(
            "Linear did not confirm the issue relation."
        )

    source_issue = relation.get("issue")
    target_issue = relation.get("relatedIssue")

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "relation_id": str(relation.get("id") or ""),
        "type": str(relation.get("type") or ""),
        "created_at": str(relation.get("createdAt") or ""),
        "issue_id": (
            str(source_issue.get("id") or "")
            if isinstance(source_issue, dict)
            else ""
        ),
        "issue_identifier": (
            str(source_issue.get("identifier") or "")
            if isinstance(source_issue, dict)
            else ""
        ),
        "related_issue_id": (
            str(target_issue.get("id") or "")
            if isinstance(target_issue, dict)
            else ""
        ),
        "related_issue_identifier": (
            str(target_issue.get("identifier") or "")
            if isinstance(target_issue, dict)
            else ""
        ),
    }, None


def linear_get_issue_history(inputs, stamp):
    """
    List an issue's audit history in receipt-safe pages: who changed what,
    and when, for the fields this module already governs (title, state,
    assignee, priority, project, cycle, parent, and labels).
    """
    issue_id = inputs.get("issue_id")
    offset = inputs.get("offset", 0)
    limit = inputs.get("limit", 10)

    if not isinstance(issue_id, str) or not issue_id.strip():
        raise RuntimeError(
            "issue_id must be a non-empty Linear UUID or identifier."
        )

    issue_id = issue_id.strip()

    if len(issue_id) > 200:
        raise RuntimeError("issue_id must be 200 characters or fewer.")

    try:
        offset = int(offset)
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "offset and limit must be integers."
        ) from exc

    if offset < 0:
        raise RuntimeError("offset must be zero or greater.")

    if limit < 1 or limit > 25:
        raise RuntimeError("limit must be between 1 and 25.")

    status, data = _graphql(
        """
        query RailCallIssueHistory($issueId: String!) {
          issue(id: $issueId) {
            history(first: 100) {
              nodes {
                id
                createdAt
                actorId
                actor {
                  id
                  name
                }
                botActor {
                  id
                  name
                }
                fromTitle
                toTitle
                fromPriority
                toPriority
                fromState {
                  id
                  name
                }
                toState {
                  id
                  name
                }
                fromAssignee {
                  id
                  name
                }
                toAssignee {
                  id
                  name
                }
                fromProject {
                  id
                  name
                }
                toProject {
                  id
                  name
                }
                fromCycle {
                  id
                  number
                  name
                }
                toCycle {
                  id
                  number
                  name
                }
                fromParent {
                  id
                  identifier
                }
                toParent {
                  id
                  identifier
                }
                addedLabels {
                  id
                  name
                }
                removedLabels {
                  id
                  name
                }
              }
            }
          }
        }
        """,
        {"issueId": issue_id},
    )

    issue = data.get("issue")
    connection = issue.get("history") if isinstance(issue, dict) else None
    nodes = connection.get("nodes") if isinstance(connection, dict) else None

    if not isinstance(nodes, list):
        raise RuntimeError(
            "Linear did not return an issue-history list."
        )

    def _entity(entry_field, id_key="id", name_key="name"):
        if not isinstance(entry_field, dict):
            return None, None
        return (
            str(entry_field.get(id_key) or "") or None,
            str(entry_field.get(name_key) or "") or None,
        )

    entries = []

    for entry in nodes:
        if not isinstance(entry, dict):
            continue

        actor = entry.get("actor")
        bot_actor = entry.get("botActor")

        from_state_id, from_state_name = _entity(entry.get("fromState"))
        to_state_id, to_state_name = _entity(entry.get("toState"))
        from_assignee_id, from_assignee_name = _entity(entry.get("fromAssignee"))
        to_assignee_id, to_assignee_name = _entity(entry.get("toAssignee"))
        from_project_id, from_project_name = _entity(entry.get("fromProject"))
        to_project_id, to_project_name = _entity(entry.get("toProject"))
        from_cycle_id, from_cycle_name = _entity(entry.get("fromCycle"))
        to_cycle_id, to_cycle_name = _entity(entry.get("toCycle"))
        from_parent_id, from_parent_identifier = _entity(
            entry.get("fromParent"), name_key="identifier"
        )
        to_parent_id, to_parent_identifier = _entity(
            entry.get("toParent"), name_key="identifier"
        )

        added_labels = entry.get("addedLabels")
        removed_labels = entry.get("removedLabels")

        entries.append({
            "id": str(entry.get("id") or ""),
            "created_at": str(entry.get("createdAt") or ""),
            "actor_id": str(entry.get("actorId") or "") or None,
            "actor_name": (
                str(actor.get("name") or "") or None
                if isinstance(actor, dict)
                else None
            ),
            "bot_actor_name": (
                str(bot_actor.get("name") or "") or None
                if isinstance(bot_actor, dict)
                else None
            ),
            "from_title": entry.get("fromTitle"),
            "to_title": entry.get("toTitle"),
            "from_priority": entry.get("fromPriority"),
            "to_priority": entry.get("toPriority"),
            "from_state_id": from_state_id,
            "from_state_name": from_state_name,
            "to_state_id": to_state_id,
            "to_state_name": to_state_name,
            "from_assignee_id": from_assignee_id,
            "from_assignee_name": from_assignee_name,
            "to_assignee_id": to_assignee_id,
            "to_assignee_name": to_assignee_name,
            "from_project_id": from_project_id,
            "from_project_name": from_project_name,
            "to_project_id": to_project_id,
            "to_project_name": to_project_name,
            "from_cycle_id": from_cycle_id,
            "from_cycle_name": from_cycle_name,
            "to_cycle_id": to_cycle_id,
            "to_cycle_name": to_cycle_name,
            "from_parent_id": from_parent_id,
            "from_parent_identifier": from_parent_identifier,
            "to_parent_id": to_parent_id,
            "to_parent_identifier": to_parent_identifier,
            "added_label_names": (
                [str(label.get("name") or "") for label in added_labels if isinstance(label, dict)]
                if isinstance(added_labels, list)
                else []
            ),
            "removed_label_names": (
                [str(label.get("name") or "") for label in removed_labels if isinstance(label, dict)]
                if isinstance(removed_labels, list)
                else []
            ),
        })

    total_count = len(entries)
    page = entries[offset:offset + limit]
    has_more = (offset + limit) < total_count

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "issue_id": issue_id,
        "entry_count": total_count,
        "returned_count": len(page),
        "next_offset": offset + len(page),
        "has_more": has_more,
        "history_json": json.dumps(
            page,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }, None


def linear_unarchive_issue(inputs, stamp):
    """Restore a previously archived Linear issue to active use."""
    issue_id = inputs.get("issue_id")

    if not isinstance(issue_id, str) or not issue_id.strip():
        raise RuntimeError(
            "issue_id must be a non-empty Linear UUID or identifier."
        )

    issue_id = issue_id.strip()

    if len(issue_id) > 200:
        raise RuntimeError("issue_id must be 200 characters or fewer.")

    status, data = _graphql(
        """
        mutation RailCallUnarchiveIssue($issueId: String!) {
          issueUnarchive(id: $issueId) {
            success
            entity {
              id
              identifier
              title
              url
            }
          }
        }
        """,
        {"issueId": issue_id},
        is_write=True,
    )

    payload = data.get("issueUnarchive")
    entity = payload.get("entity") if isinstance(payload, dict) else None

    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise RuntimeError(
            "Linear did not confirm the issue unarchive."
        )

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "issue_id": (
            str(entity.get("id") or "") if isinstance(entity, dict) else issue_id
        ),
        "identifier": (
            str(entity.get("identifier") or "") if isinstance(entity, dict) else ""
        ),
        "title": str(entity.get("title") or "") if isinstance(entity, dict) else "",
        "url": str(entity.get("url") or "") if isinstance(entity, dict) else "",
        "unarchived": True,
    }, None


def linear_update_label(inputs, stamp):
    """Rename, recolor, or redescribe an existing Linear issue label."""
    label_id = inputs.get("label_id")

    if not isinstance(label_id, str) or not label_id.strip():
        raise RuntimeError(
            "label_id must be a non-empty Linear label UUID."
        )

    label_id = label_id.strip()

    if len(label_id) > 200:
        raise RuntimeError("label_id must be 200 characters or fewer.")

    label_input = {}

    if "name" in inputs:
        name = inputs.get("name")
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError(
                "name must be a non-empty string when supplied."
            )
        name = name.strip()
        if len(name) > 255:
            raise RuntimeError("name must be 255 characters or fewer.")
        label_input["name"] = name

    if "color" in inputs:
        color = inputs.get("color")
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color.strip()):
            raise RuntimeError(
                "color must be a hex color like #4EA7FC when supplied."
            )
        label_input["color"] = color.strip()

    if "description" in inputs:
        description = inputs.get("description")
        if not isinstance(description, str):
            raise RuntimeError(
                "description must be a string when supplied."
            )
        if len(description) > 2000:
            raise RuntimeError("description must be 2000 characters or fewer.")
        label_input["description"] = description

    if not label_input:
        raise RuntimeError(
            "Supply at least one field to update: name, color, or description."
        )

    status, data = _graphql(
        """
        mutation RailCallUpdateLabel($labelId: String!, $input: IssueLabelUpdateInput!) {
          issueLabelUpdate(id: $labelId, input: $input) {
            success
            issueLabel {
              id
              name
              color
              description
              isGroup
            }
          }
        }
        """,
        {"labelId": label_id, "input": label_input},
        is_write=True,
    )

    payload = data.get("issueLabelUpdate")
    label = payload.get("issueLabel") if isinstance(payload, dict) else None

    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(label, dict)
    ):
        raise RuntimeError(
            "Linear did not confirm the label update."
        )

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "label_id": str(label.get("id") or ""),
        "name": str(label.get("name") or ""),
        "color": str(label.get("color") or ""),
        "description": str(label.get("description") or ""),
        "is_group": bool(label.get("isGroup")),
    }, None


def linear_delete_attachment(inputs, stamp):
    """Delete an attachment from a Linear issue."""
    attachment_id = inputs.get("attachment_id")

    if not isinstance(attachment_id, str) or not attachment_id.strip():
        raise RuntimeError(
            "attachment_id must be a non-empty Linear attachment UUID."
        )

    attachment_id = attachment_id.strip()

    if len(attachment_id) > 200:
        raise RuntimeError("attachment_id must be 200 characters or fewer.")

    status, data = _graphql(
        """
        mutation RailCallDeleteAttachment($attachmentId: String!) {
          attachmentDelete(id: $attachmentId) {
            success
            entityId
          }
        }
        """,
        {"attachmentId": attachment_id},
        is_write=True,
    )

    payload = data.get("attachmentDelete")

    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise RuntimeError(
            "Linear did not confirm the attachment delete."
        )

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "attachment_id": str(payload.get("entityId") or attachment_id),
        "deleted": True,
    }, None


def linear_unlink_issues(inputs, stamp):
    """Remove an existing relation between two Linear issues."""
    relation_id = inputs.get("relation_id")

    if not isinstance(relation_id, str) or not relation_id.strip():
        raise RuntimeError(
            "relation_id must be a non-empty Linear issue-relation UUID."
        )

    relation_id = relation_id.strip()

    if len(relation_id) > 200:
        raise RuntimeError("relation_id must be 200 characters or fewer.")

    status, data = _graphql(
        """
        mutation RailCallUnlinkIssues($relationId: String!) {
          issueRelationDelete(id: $relationId) {
            success
            entityId
          }
        }
        """,
        {"relationId": relation_id},
        is_write=True,
    )

    payload = data.get("issueRelationDelete")

    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise RuntimeError(
            "Linear did not confirm the issue-relation delete."
        )

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "relation_id": str(payload.get("entityId") or relation_id),
        "unlinked": True,
    }, None


def linear_resolve_comment(inputs, stamp):
    """Mark a Linear comment thread as resolved."""
    comment_id = inputs.get("comment_id")

    if not isinstance(comment_id, str) or not comment_id.strip():
        raise RuntimeError(
            "comment_id must be a non-empty Linear comment UUID."
        )

    comment_id = comment_id.strip()

    if len(comment_id) > 200:
        raise RuntimeError("comment_id must be 200 characters or fewer.")

    status, data = _graphql(
        """
        mutation RailCallResolveComment($commentId: String!) {
          commentResolve(id: $commentId) {
            success
            comment {
              id
              resolvedAt
            }
          }
        }
        """,
        {"commentId": comment_id},
        is_write=True,
    )

    payload = data.get("commentResolve")
    comment = payload.get("comment") if isinstance(payload, dict) else None

    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(comment, dict)
    ):
        raise RuntimeError(
            "Linear did not confirm the comment resolve."
        )

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "comment_id": str(comment.get("id") or ""),
        "resolved_at": str(comment.get("resolvedAt") or ""),
    }, None


def linear_unresolve_comment(inputs, stamp):
    """Reopen a resolved Linear comment thread."""
    comment_id = inputs.get("comment_id")

    if not isinstance(comment_id, str) or not comment_id.strip():
        raise RuntimeError(
            "comment_id must be a non-empty Linear comment UUID."
        )

    comment_id = comment_id.strip()

    if len(comment_id) > 200:
        raise RuntimeError("comment_id must be 200 characters or fewer.")

    status, data = _graphql(
        """
        mutation RailCallUnresolveComment($commentId: String!) {
          commentUnresolve(id: $commentId) {
            success
            comment {
              id
              resolvedAt
            }
          }
        }
        """,
        {"commentId": comment_id},
        is_write=True,
    )

    payload = data.get("commentUnresolve")
    comment = payload.get("comment") if isinstance(payload, dict) else None

    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(comment, dict)
    ):
        raise RuntimeError(
            "Linear did not confirm the comment unresolve."
        )

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "comment_id": str(comment.get("id") or ""),
        "resolved_at": str(comment.get("resolvedAt") or ""),
    }, None


def linear_create_cycle(inputs, stamp):
    """Create a Linear cycle (sprint) for one team."""
    team_id = inputs.get("team_id")
    starts_at = inputs.get("starts_at")
    ends_at = inputs.get("ends_at")
    name = inputs.get("name")
    description = inputs.get("description")

    if not isinstance(team_id, str) or not team_id.strip():
        raise RuntimeError(
            "team_id must be a non-empty Linear team UUID."
        )

    if not isinstance(starts_at, str) or not starts_at.strip():
        raise RuntimeError(
            "starts_at must be a non-empty ISO 8601 datetime string."
        )

    if not isinstance(ends_at, str) or not ends_at.strip():
        raise RuntimeError(
            "ends_at must be a non-empty ISO 8601 datetime string."
        )

    team_id = team_id.strip()
    starts_at = starts_at.strip()
    ends_at = ends_at.strip()

    if len(team_id) > 200:
        raise RuntimeError("team_id must be 200 characters or fewer.")

    cycle_input = {
        "teamId": team_id,
        "startsAt": starts_at,
        "endsAt": ends_at,
    }

    if name is not None:
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError(
                "name must be a non-empty string when supplied."
            )
        name = name.strip()
        if len(name) > 255:
            raise RuntimeError("name must be 255 characters or fewer.")
        cycle_input["name"] = name

    if description is not None:
        if not isinstance(description, str):
            raise RuntimeError(
                "description must be a string when supplied."
            )
        if len(description) > 2000:
            raise RuntimeError("description must be 2000 characters or fewer.")
        cycle_input["description"] = description

    status, data = _graphql(
        """
        mutation RailCallCreateCycle($input: CycleCreateInput!) {
          cycleCreate(input: $input) {
            success
            cycle {
              id
              number
              name
              startsAt
              endsAt
              completedAt
            }
          }
        }
        """,
        {"input": cycle_input},
        is_write=True,
    )

    payload = data.get("cycleCreate")
    cycle = payload.get("cycle") if isinstance(payload, dict) else None

    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(cycle, dict)
    ):
        raise RuntimeError(
            "Linear did not confirm cycle creation."
        )

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "cycle_id": str(cycle.get("id") or ""),
        "number": (
            int(cycle.get("number"))
            if isinstance(cycle.get("number"), (int, float))
            else 0
        ),
        "name": str(cycle.get("name") or ""),
        "starts_at": str(cycle.get("startsAt") or ""),
        "ends_at": str(cycle.get("endsAt") or ""),
        "completed_at": str(cycle.get("completedAt") or ""),
    }, None


def linear_update_cycle(inputs, stamp):
    """Update selected fields on one existing Linear cycle."""
    cycle_id = inputs.get("cycle_id")

    if not isinstance(cycle_id, str) or not cycle_id.strip():
        raise RuntimeError(
            "cycle_id must be a non-empty Linear cycle UUID."
        )

    cycle_id = cycle_id.strip()

    if len(cycle_id) > 200:
        raise RuntimeError("cycle_id must be 200 characters or fewer.")

    update_input = {}

    if "name" in inputs:
        name = inputs.get("name")
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError(
                "name must be a non-empty string when supplied."
            )
        name = name.strip()
        if len(name) > 255:
            raise RuntimeError("name must be 255 characters or fewer.")
        update_input["name"] = name

    if "description" in inputs:
        description = inputs.get("description")
        if not isinstance(description, str):
            raise RuntimeError(
                "description must be a string when supplied."
            )
        if len(description) > 2000:
            raise RuntimeError("description must be 2000 characters or fewer.")
        update_input["description"] = description

    if "starts_at" in inputs:
        starts_at = inputs.get("starts_at")
        if not isinstance(starts_at, str) or not starts_at.strip():
            raise RuntimeError(
                "starts_at must be a non-empty ISO 8601 datetime string when supplied."
            )
        update_input["startsAt"] = starts_at.strip()

    if "ends_at" in inputs:
        ends_at = inputs.get("ends_at")
        if not isinstance(ends_at, str) or not ends_at.strip():
            raise RuntimeError(
                "ends_at must be a non-empty ISO 8601 datetime string when supplied."
            )
        update_input["endsAt"] = ends_at.strip()

    if "completed_at" in inputs:
        completed_at = inputs.get("completed_at")
        if not isinstance(completed_at, str) or not completed_at.strip():
            raise RuntimeError(
                "completed_at must be a non-empty ISO 8601 datetime string when supplied."
            )
        update_input["completedAt"] = completed_at.strip()

    if not update_input:
        raise RuntimeError(
            "Supply at least one field to update: name, description, "
            "starts_at, ends_at, or completed_at."
        )

    status, data = _graphql(
        """
        mutation RailCallUpdateCycle($cycleId: String!, $input: CycleUpdateInput!) {
          cycleUpdate(id: $cycleId, input: $input) {
            success
            cycle {
              id
              number
              name
              startsAt
              endsAt
              completedAt
            }
          }
        }
        """,
        {"cycleId": cycle_id, "input": update_input},
        is_write=True,
    )

    payload = data.get("cycleUpdate")
    cycle = payload.get("cycle") if isinstance(payload, dict) else None

    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(cycle, dict)
    ):
        raise RuntimeError(
            "Linear did not confirm the cycle update."
        )

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": status,
        "cycle_id": str(cycle.get("id") or ""),
        "number": (
            int(cycle.get("number"))
            if isinstance(cycle.get("number"), (int, float))
            else 0
        ),
        "name": str(cycle.get("name") or ""),
        "starts_at": str(cycle.get("startsAt") or ""),
        "ends_at": str(cycle.get("endsAt") or ""),
        "completed_at": str(cycle.get("completedAt") or ""),
    }, None


def _optional_boolean(inputs, name):
    """Read one optional boolean from RailCall form or JSON inputs."""
    if name not in inputs:
        return False
    value = inputs.get(name)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    raise RuntimeError(f"{name} must be true or false when supplied.")


def _optional_linear_id(inputs, name, description):
    """Return a trimmed optional Linear identifier with a conservative cap."""
    if name not in inputs:
        return None
    value = inputs.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{name} must be a non-empty {description} when supplied.")
    value = value.strip()
    if len(value) > 200:
        raise RuntimeError(f"{name} must be 200 characters or fewer.")
    return value


def _parse_label_ids_json(value):
    """Parse an exact replacement label set from a bounded JSON array."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError("label_ids_json must be a JSON array string.")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "label_ids_json must be valid JSON, for example [\"label-uuid\"]."
        ) from exc
    if not isinstance(parsed, list):
        raise RuntimeError("label_ids_json must decode to a JSON array.")
    if len(parsed) > 5:
        raise RuntimeError("label_ids_json may contain at most 5 labels.")

    label_ids = []
    seen = set()
    for index, item in enumerate(parsed):
        if not isinstance(item, str) or not item.strip():
            raise RuntimeError(
                f"label_ids_json item {index + 1} must be a non-empty label UUID."
            )
        item = item.strip()
        if len(item) > 200:
            raise RuntimeError("Each label UUID must be 200 characters or fewer.")
        if item not in seen:
            seen.add(item)
            label_ids.append(item)
    return label_ids


def _entity_summary(entity):
    if not isinstance(entity, dict):
        return None
    result = {
        "id": str(entity.get("id") or ""),
        "name": str(entity.get("name") or ""),
    }
    return result


def linear_triage_issue(inputs, stamp):
    """Apply one bounded, approval-controlled triage decision to an issue."""
    issue_id = _optional_linear_id(
        inputs,
        "issue_id",
        "Linear issue UUID or identifier",
    )
    if issue_id is None:
        raise RuntimeError(
            "issue_id must be a non-empty Linear UUID or identifier."
        )

    state_id = _optional_linear_id(
        inputs,
        "state_id",
        "Linear workflow-state UUID",
    )
    assignee_id = _optional_linear_id(
        inputs,
        "assignee_id",
        "Linear workspace-member UUID",
    )
    project_id = _optional_linear_id(
        inputs,
        "project_id",
        "Linear project UUID",
    )
    cycle_id = _optional_linear_id(
        inputs,
        "cycle_id",
        "Linear cycle UUID",
    )

    clear_assignee = _optional_boolean(inputs, "clear_assignee")
    clear_project = _optional_boolean(inputs, "clear_project")
    clear_cycle = _optional_boolean(inputs, "clear_cycle")

    if assignee_id is not None and clear_assignee:
        raise RuntimeError(
            "Supply assignee_id or clear_assignee=true, not both."
        )
    if project_id is not None and clear_project:
        raise RuntimeError(
            "Supply project_id or clear_project=true, not both."
        )
    if cycle_id is not None and clear_cycle:
        raise RuntimeError(
            "Supply cycle_id or clear_cycle=true, not both."
        )

    priority = None
    if "priority" in inputs:
        raw_priority = inputs.get("priority")
        if isinstance(raw_priority, bool):
            raise RuntimeError("priority must be an integer from 0 to 4.")
        try:
            priority = int(raw_priority)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("priority must be an integer from 0 to 4.") from exc
        if priority < 0 or priority > 4:
            raise RuntimeError("priority must be between 0 and 4.")

    label_ids = None
    if "label_ids_json" in inputs:
        label_ids = _parse_label_ids_json(inputs.get("label_ids_json"))

    triage_note = ""
    if "triage_note" in inputs:
        value = inputs.get("triage_note")
        if not isinstance(value, str):
            raise RuntimeError("triage_note must be a string when supplied.")
        triage_note = value.strip()
        if len(triage_note) > 2000:
            raise RuntimeError("triage_note must be 2000 characters or fewer.")

    requested_property_change = any(
        (
            priority is not None,
            state_id is not None,
            assignee_id is not None,
            clear_assignee,
            project_id is not None,
            clear_project,
            cycle_id is not None,
            clear_cycle,
            label_ids is not None,
        )
    )
    if not requested_property_change:
        raise RuntimeError(
            "Supply at least one triage property: priority, state_id, "
            "assignee_id/clear_assignee, project_id/clear_project, "
            "cycle_id/clear_cycle, or label_ids_json."
        )

    variable_definitions = ["$issueId: String!"]
    query_fields = [
        """
        issue: issue(id: $issueId) {
          id
          identifier
          title
          url
          priority
          updatedAt
          state { id name type team { id name } }
          assignee { id name }
          project { id name archivedAt }
          cycle { id number name completedAt team { id name } }
          labels(first: 20) {
            nodes { id name isGroup archivedAt team { id name } }
          }
          team { id name key }
        }
        """
    ]
    variables = {"issueId": issue_id}

    if assignee_id is not None:
        variable_definitions.append("$assigneeId: String!")
        query_fields.append(
            "targetAssignee: user(id: $assigneeId) { id name }"
        )
        variables["assigneeId"] = assignee_id
    if state_id is not None:
        variable_definitions.append("$stateId: String!")
        query_fields.append(
            "targetState: workflowState(id: $stateId) { "
            "id name type archivedAt team { id name } }"
        )
        variables["stateId"] = state_id
    if project_id is not None:
        variable_definitions.append("$projectId: String!")
        query_fields.append(
            "targetProject: project(id: $projectId) { id name archivedAt teamIds }"
        )
        variables["projectId"] = project_id
    if cycle_id is not None:
        variable_definitions.append("$cycleId: String!")
        query_fields.append(
            "targetCycle: cycle(id: $cycleId) { "
            "id number name completedAt team { id name } }"
        )
        variables["cycleId"] = cycle_id
    if label_ids is not None:
        for index, label_id in enumerate(label_ids):
            variable_name = f"labelId{index}"
            variable_definitions.append(f"${variable_name}: String!")
            query_fields.append(
                f"targetLabel{index}: issueLabel(id: ${variable_name}) {{ "
                "id name isGroup archivedAt team { id name } }"
            )
            variables[variable_name] = label_id

    preflight_query = (
        "query RailCallTriagePreflight("
        + ", ".join(variable_definitions)
        + ") {\n"
        + "\n".join(query_fields)
        + "\n}"
    )
    preflight_status, preflight_data = _graphql(
        preflight_query,
        variables,
    )

    issue = preflight_data.get("issue")
    if not isinstance(issue, dict):
        raise RuntimeError(f"Linear issue {issue_id!r} was not found.")
    team = issue.get("team")
    if not isinstance(team, dict) or not str(team.get("id") or ""):
        raise RuntimeError("Linear did not return the issue's team.")
    issue_team_id = str(team.get("id") or "")

    target_assignee = preflight_data.get("targetAssignee")
    if assignee_id is not None and not isinstance(target_assignee, dict):
        raise RuntimeError(f"Linear workspace member {assignee_id!r} was not found.")

    target_state = preflight_data.get("targetState")
    if state_id is not None:
        if not isinstance(target_state, dict):
            raise RuntimeError(f"Linear workflow state {state_id!r} was not found.")
        if target_state.get("archivedAt"):
            raise RuntimeError("The selected workflow state is archived.")
        state_team = target_state.get("team")
        state_team_id = (
            str(state_team.get("id") or "")
            if isinstance(state_team, dict)
            else ""
        )
        if state_team_id != issue_team_id:
            raise RuntimeError(
                "The selected workflow state does not belong to the issue's team."
            )

    target_project = preflight_data.get("targetProject")
    if project_id is not None:
        if not isinstance(target_project, dict):
            raise RuntimeError(f"Linear project {project_id!r} was not found.")
        if target_project.get("archivedAt"):
            raise RuntimeError("The selected project is archived.")
        project_team_ids = target_project.get("teamIds")
        if not isinstance(project_team_ids, list):
            raise RuntimeError(
                "Linear did not return the selected project's team scope."
            )
        if issue_team_id not in {str(item) for item in project_team_ids}:
            raise RuntimeError(
                "The selected project is not associated with the issue's team."
            )

    target_cycle = preflight_data.get("targetCycle")
    if cycle_id is not None:
        if not isinstance(target_cycle, dict):
            raise RuntimeError(f"Linear cycle {cycle_id!r} was not found.")
        cycle_team = target_cycle.get("team")
        cycle_team_id = (
            str(cycle_team.get("id") or "")
            if isinstance(cycle_team, dict)
            else ""
        )
        if cycle_team_id != issue_team_id:
            raise RuntimeError(
                "The selected cycle does not belong to the issue's team."
            )
        if target_cycle.get("completedAt"):
            raise RuntimeError("The selected cycle is already completed.")

    target_labels = []
    if label_ids is not None:
        for index, label_id in enumerate(label_ids):
            label = preflight_data.get(f"targetLabel{index}")
            if not isinstance(label, dict):
                raise RuntimeError(f"Linear issue label {label_id!r} was not found.")
            if label.get("archivedAt"):
                raise RuntimeError(
                    f"The selected label {str(label.get('name') or label_id)!r} is archived."
                )
            if label.get("isGroup") is True:
                raise RuntimeError(
                    f"The selected label {str(label.get('name') or label_id)!r} is a label group and cannot be applied."
                )
            label_team = label.get("team")
            label_team_id = (
                str(label_team.get("id") or "")
                if isinstance(label_team, dict)
                else ""
            )
            if label_team_id and label_team_id != issue_team_id:
                raise RuntimeError(
                    f"The selected label {str(label.get('name') or label_id)!r} belongs to another team."
                )
            target_labels.append(label)

    current_state = issue.get("state")
    current_assignee = issue.get("assignee")
    current_project = issue.get("project")
    current_cycle = issue.get("cycle")
    current_labels_connection = issue.get("labels")
    current_label_nodes = (
        current_labels_connection.get("nodes")
        if isinstance(current_labels_connection, dict)
        else []
    )
    if not isinstance(current_label_nodes, list):
        current_label_nodes = []

    update_input = {}
    changes = []

    current_priority = issue.get("priority")
    current_priority = (
        int(current_priority)
        if isinstance(current_priority, (int, float))
        else 0
    )
    if priority is not None and priority != current_priority:
        update_input["priority"] = priority
        changes.append({
            "field": "priority",
            "before": current_priority,
            "after": priority,
        })

    current_state_id = (
        str(current_state.get("id") or "")
        if isinstance(current_state, dict)
        else ""
    )
    if state_id is not None and state_id != current_state_id:
        update_input["stateId"] = state_id
        changes.append({
            "field": "state",
            "before": _entity_summary(current_state),
            "after": _entity_summary(target_state),
        })

    current_assignee_id = (
        str(current_assignee.get("id") or "")
        if isinstance(current_assignee, dict)
        else ""
    )
    if clear_assignee and current_assignee_id:
        update_input["assigneeId"] = None
        changes.append({
            "field": "assignee",
            "before": _entity_summary(current_assignee),
            "after": None,
        })
    elif assignee_id is not None and assignee_id != current_assignee_id:
        update_input["assigneeId"] = assignee_id
        changes.append({
            "field": "assignee",
            "before": _entity_summary(current_assignee),
            "after": _entity_summary(target_assignee),
        })

    current_project_id = (
        str(current_project.get("id") or "")
        if isinstance(current_project, dict)
        else ""
    )
    if clear_project and current_project_id:
        update_input["projectId"] = None
        changes.append({
            "field": "project",
            "before": _entity_summary(current_project),
            "after": None,
        })
    elif project_id is not None and project_id != current_project_id:
        update_input["projectId"] = project_id
        changes.append({
            "field": "project",
            "before": _entity_summary(current_project),
            "after": _entity_summary(target_project),
        })

    current_cycle_id = (
        str(current_cycle.get("id") or "")
        if isinstance(current_cycle, dict)
        else ""
    )
    if clear_cycle and current_cycle_id:
        update_input["cycleId"] = None
        changes.append({
            "field": "cycle",
            "before": _entity_summary(current_cycle),
            "after": None,
        })
    elif cycle_id is not None and cycle_id != current_cycle_id:
        update_input["cycleId"] = cycle_id
        changes.append({
            "field": "cycle",
            "before": _entity_summary(current_cycle),
            "after": _entity_summary(target_cycle),
        })

    current_label_ids = {
        str(label.get("id") or "")
        for label in current_label_nodes
        if isinstance(label, dict) and str(label.get("id") or "")
    }
    if label_ids is not None and set(label_ids) != current_label_ids:
        update_input["labelIds"] = label_ids
        changes.append({
            "field": "labels",
            "before": [
                _entity_summary(label)
                for label in current_label_nodes
                if isinstance(label, dict)
            ],
            "after": [_entity_summary(label) for label in target_labels],
        })

    if not update_input:
        raise RuntimeError(
            "The requested triage properties already match the issue. "
            "No Linear write was attempted."
        )

    update_status, update_data = _graphql(
        """
        mutation RailCallTriageIssue(
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
              state { id name type }
              assignee { id name }
              project { id name }
              cycle { id number name }
              labels(first: 20) { nodes { id name } }
              team { id name key }
            }
          }
        }
        """,
        {"issueId": issue_id, "input": update_input},
        is_write=True,
    )

    payload = update_data.get("issueUpdate")
    updated_issue = payload.get("issue") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(updated_issue, dict)
    ):
        raise RuntimeError("Linear did not confirm the triage issue update.")

    completed_steps = ["issue_update"]
    comment_id = ""
    comment_status = 0
    if triage_note:
        try:
            comment_status, comment_data = _graphql(
                """
                mutation RailCallTriageComment($input: CommentCreateInput!) {
                  commentCreate(input: $input) {
                    success
                    comment { id createdAt body }
                  }
                }
                """,
                {"input": {"issueId": issue_id, "body": triage_note}},
                is_write=True,
            )
            comment_payload = comment_data.get("commentCreate")
            comment = (
                comment_payload.get("comment")
                if isinstance(comment_payload, dict)
                else None
            )
            if (
                not isinstance(comment_payload, dict)
                or comment_payload.get("success") is not True
                or not isinstance(comment, dict)
            ):
                raise RuntimeError("Linear did not confirm the triage comment.")
            comment_id = str(comment.get("id") or "")
            completed_steps.append("triage_comment")
        except RuntimeError as exc:
            identifier = str(updated_issue.get("identifier") or issue_id)
            fields = ", ".join(change["field"] for change in changes)
            raise RuntimeError(
                f"Linear issue {identifier} was updated successfully for "
                f"field(s): {fields}, but the triage comment was not fully "
                "confirmed. Do not rerun the entire triage command blindly. "
                "Inspect the issue in Linear and add the note separately if "
                f"needed. Detail: {_redact(exc)}"
            ) from None

    result_state = updated_issue.get("state")
    result_assignee = updated_issue.get("assignee")
    result_project = updated_issue.get("project")
    result_cycle = updated_issue.get("cycle")
    result_labels_connection = updated_issue.get("labels")
    result_label_nodes = (
        result_labels_connection.get("nodes")
        if isinstance(result_labels_connection, dict)
        else []
    )
    if not isinstance(result_label_nodes, list):
        result_label_nodes = []

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": update_status,
        "comment_http_status": comment_status,
        "operation": "triage_issue",
        "issue_id": str(updated_issue.get("id") or ""),
        "identifier": str(updated_issue.get("identifier") or ""),
        "title": str(updated_issue.get("title") or ""),
        "url": str(updated_issue.get("url") or ""),
        "updated_at": str(updated_issue.get("updatedAt") or ""),
        "priority": (
            int(updated_issue.get("priority"))
            if isinstance(updated_issue.get("priority"), (int, float))
            else 0
        ),
        "state_json": json.dumps(
            _entity_summary(result_state),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "assignee_json": json.dumps(
            _entity_summary(result_assignee),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "project_json": json.dumps(
            _entity_summary(result_project),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "cycle_json": json.dumps(
            _entity_summary(result_cycle),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "labels_json": json.dumps(
            [
                _entity_summary(label)
                for label in result_label_nodes
                if isinstance(label, dict)
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "changes_applied_json": json.dumps(
            changes,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "completed_steps_json": json.dumps(
            completed_steps,
            separators=(",", ":"),
        ),
        "triage_note_added": bool(triage_note),
        "comment_id": comment_id,
        "preflight_http_status": preflight_status,
    }, None


def _parse_sprint_plan_issues_json(value):
    """Parse a bounded multi-issue sprint plan from one exact JSON payload."""
    if not isinstance(value, str):
        raise RuntimeError("issues_json must be a JSON array string.")
    if len(value) > 40000:
        raise RuntimeError("issues_json must be 40000 characters or fewer.")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "issues_json must be valid JSON containing 2 to 5 issue objects."
        ) from exc
    if not isinstance(parsed, list):
        raise RuntimeError("issues_json must decode to a JSON array.")
    if len(parsed) < 2 or len(parsed) > 5:
        raise RuntimeError("issues_json must contain between 2 and 5 issues.")

    allowed_fields = {
        "title",
        "description",
        "priority",
        "estimate",
        "assignee_id",
        "label_ids",
    }
    normalized = []
    seen_titles = set()
    total_description_chars = 0

    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"issues_json item {index} must be an object.")
        unknown = sorted(set(item) - allowed_fields)
        if unknown:
            raise RuntimeError(
                f"issues_json item {index} contains unsupported field(s): "
                + ", ".join(unknown)
            )

        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            raise RuntimeError(
                f"issues_json item {index} requires a non-empty title."
            )
        title = title.strip()
        if len(title) > 255:
            raise RuntimeError(
                f"issues_json item {index} title must be 255 characters or fewer."
            )
        title_key = title.casefold()
        if title_key in seen_titles:
            raise RuntimeError("issues_json issue titles must be unique within the plan.")
        seen_titles.add(title_key)

        description = item.get("description", "")
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise RuntimeError(
                f"issues_json item {index} description must be a string."
            )
        if len(description) > 10000:
            raise RuntimeError(
                f"issues_json item {index} description must be 10000 characters or fewer."
            )
        total_description_chars += len(description)
        if total_description_chars > 25000:
            raise RuntimeError(
                "The combined issue descriptions must be 25000 characters or fewer."
            )

        priority = None
        if "priority" in item:
            raw_priority = item.get("priority")
            if isinstance(raw_priority, bool):
                raise RuntimeError(
                    f"issues_json item {index} priority must be an integer from 0 to 4."
                )
            try:
                priority = int(raw_priority)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"issues_json item {index} priority must be an integer from 0 to 4."
                ) from exc
            if priority < 0 or priority > 4:
                raise RuntimeError(
                    f"issues_json item {index} priority must be between 0 and 4."
                )

        estimate = None
        if "estimate" in item:
            raw_estimate = item.get("estimate")
            if isinstance(raw_estimate, bool):
                raise RuntimeError(
                    f"issues_json item {index} estimate must be an integer from 0 to 100."
                )
            try:
                estimate = int(raw_estimate)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"issues_json item {index} estimate must be an integer from 0 to 100."
                ) from exc
            if estimate < 0 or estimate > 100:
                raise RuntimeError(
                    f"issues_json item {index} estimate must be between 0 and 100."
                )

        assignee_id = item.get("assignee_id")
        if assignee_id is not None:
            if not isinstance(assignee_id, str) or not assignee_id.strip():
                raise RuntimeError(
                    f"issues_json item {index} assignee_id must be a non-empty UUID."
                )
            assignee_id = assignee_id.strip()
            if len(assignee_id) > 200:
                raise RuntimeError("Assignee UUIDs must be 200 characters or fewer.")

        raw_label_ids = item.get("label_ids", [])
        if raw_label_ids is None:
            raw_label_ids = []
        if not isinstance(raw_label_ids, list):
            raise RuntimeError(
                f"issues_json item {index} label_ids must be a JSON array."
            )
        if len(raw_label_ids) > 5:
            raise RuntimeError(
                f"issues_json item {index} may contain at most 5 labels."
            )
        label_ids = []
        seen_labels = set()
        for label_index, label_id in enumerate(raw_label_ids, start=1):
            if not isinstance(label_id, str) or not label_id.strip():
                raise RuntimeError(
                    f"issues_json item {index} label {label_index} must be a non-empty UUID."
                )
            label_id = label_id.strip()
            if len(label_id) > 200:
                raise RuntimeError("Label UUIDs must be 200 characters or fewer.")
            if label_id not in seen_labels:
                seen_labels.add(label_id)
                label_ids.append(label_id)

        normalized.append({
            "request_index": index,
            "title": title,
            "description": description,
            "priority": priority,
            "estimate": estimate,
            "assignee_id": assignee_id,
            "label_ids": label_ids,
        })

    unique_assignees = {
        issue["assignee_id"]
        for issue in normalized
        if issue["assignee_id"] is not None
    }
    unique_labels = {
        label_id
        for issue in normalized
        for label_id in issue["label_ids"]
    }
    if len(unique_assignees) > 5:
        raise RuntimeError("A sprint plan may reference at most 5 assignees.")
    if len(unique_labels) > 20:
        raise RuntimeError("A sprint plan may reference at most 20 unique labels.")

    return normalized


def linear_plan_sprint(inputs, stamp):
    """Create a bounded sprint issue set in one Linear transaction."""
    team_id = _optional_linear_id(inputs, "team_id", "Linear team UUID")
    cycle_id = _optional_linear_id(inputs, "cycle_id", "Linear cycle UUID")
    project_id = _optional_linear_id(inputs, "project_id", "Linear project UUID")
    state_id = _optional_linear_id(
        inputs,
        "state_id",
        "Linear workflow-state UUID",
    )
    parent_issue_id = _optional_linear_id(
        inputs,
        "parent_issue_id",
        "parent Linear issue UUID or identifier",
    )
    if team_id is None:
        raise RuntimeError("team_id must be a non-empty Linear team UUID.")
    if cycle_id is None:
        raise RuntimeError("cycle_id must be a non-empty Linear cycle UUID.")

    issues = _parse_sprint_plan_issues_json(inputs.get("issues_json"))
    assignee_ids = sorted({
        issue["assignee_id"]
        for issue in issues
        if issue["assignee_id"] is not None
    })
    label_ids = sorted({
        label_id
        for issue in issues
        for label_id in issue["label_ids"]
    })

    variable_definitions = ["$teamId: String!", "$cycleId: String!"]
    query_fields = [
        "team: team(id: $teamId) { id name key }",
        (
            "cycle: cycle(id: $cycleId) { id number name startsAt endsAt "
            "completedAt team { id name } }"
        ),
    ]
    variables = {"teamId": team_id, "cycleId": cycle_id}

    if project_id is not None:
        variable_definitions.append("$projectId: String!")
        query_fields.append(
            "targetProject: project(id: $projectId) { id name archivedAt teamIds }"
        )
        variables["projectId"] = project_id
    if state_id is not None:
        variable_definitions.append("$stateId: String!")
        query_fields.append(
            "targetState: workflowState(id: $stateId) { "
            "id name type archivedAt team { id name } }"
        )
        variables["stateId"] = state_id
    if parent_issue_id is not None:
        variable_definitions.append("$parentIssueId: String!")
        query_fields.append(
            "parentIssue: issue(id: $parentIssueId) { "
            "id identifier title archivedAt team { id name } }"
        )
        variables["parentIssueId"] = parent_issue_id

    for index, assignee_id in enumerate(assignee_ids):
        variable_name = f"assigneeId{index}"
        variable_definitions.append(f"${variable_name}: String!")
        query_fields.append(
            f"targetAssignee{index}: user(id: ${variable_name}) {{ id name }}"
        )
        variables[variable_name] = assignee_id
    for index, label_id in enumerate(label_ids):
        variable_name = f"labelId{index}"
        variable_definitions.append(f"${variable_name}: String!")
        query_fields.append(
            f"targetLabel{index}: issueLabel(id: ${variable_name}) {{ "
            "id name isGroup archivedAt team { id name } }"
        )
        variables[variable_name] = label_id

    preflight_query = (
        "query RailCallPlanSprintPreflight("
        + ", ".join(variable_definitions)
        + ") {\n"
        + "\n".join(query_fields)
        + "\n}"
    )
    preflight_status, preflight_data = _graphql(preflight_query, variables)

    team = preflight_data.get("team")
    if not isinstance(team, dict):
        raise RuntimeError(f"Linear team {team_id!r} was not found.")
    resolved_team_id = str(team.get("id") or "")
    if not resolved_team_id:
        raise RuntimeError("Linear did not return the selected team identifier.")

    cycle = preflight_data.get("cycle")
    if not isinstance(cycle, dict):
        raise RuntimeError(f"Linear cycle {cycle_id!r} was not found.")
    cycle_team = cycle.get("team")
    cycle_team_id = (
        str(cycle_team.get("id") or "")
        if isinstance(cycle_team, dict)
        else ""
    )
    if cycle_team_id != resolved_team_id:
        raise RuntimeError("The selected cycle does not belong to the selected team.")
    if cycle.get("completedAt"):
        raise RuntimeError("The selected cycle is already completed.")
    cycle_end = _parse_linear_datetime(cycle.get("endsAt"))
    if cycle_end is not None and cycle_end < datetime.now(timezone.utc):
        raise RuntimeError("The selected cycle has already ended.")

    target_project = preflight_data.get("targetProject")
    if project_id is not None:
        if not isinstance(target_project, dict):
            raise RuntimeError(f"Linear project {project_id!r} was not found.")
        if target_project.get("archivedAt"):
            raise RuntimeError("The selected project is archived.")
        project_team_ids = target_project.get("teamIds")
        if not isinstance(project_team_ids, list):
            raise RuntimeError("Linear did not return the selected project's teams.")
        if resolved_team_id not in {str(item) for item in project_team_ids}:
            raise RuntimeError("The selected project is not linked to the selected team.")

    target_state = preflight_data.get("targetState")
    if state_id is not None:
        if not isinstance(target_state, dict):
            raise RuntimeError(f"Linear workflow state {state_id!r} was not found.")
        if target_state.get("archivedAt"):
            raise RuntimeError("The selected workflow state is archived.")
        state_team = target_state.get("team")
        state_team_id = (
            str(state_team.get("id") or "")
            if isinstance(state_team, dict)
            else ""
        )
        if state_team_id != resolved_team_id:
            raise RuntimeError(
                "The selected workflow state does not belong to the selected team."
            )

    parent_issue = preflight_data.get("parentIssue")
    if parent_issue_id is not None:
        if not isinstance(parent_issue, dict):
            raise RuntimeError(
                f"Linear parent issue {parent_issue_id!r} was not found."
            )
        if parent_issue.get("archivedAt"):
            raise RuntimeError("The selected parent issue is archived.")
        parent_team = parent_issue.get("team")
        parent_team_id = (
            str(parent_team.get("id") or "")
            if isinstance(parent_team, dict)
            else ""
        )
        if parent_team_id != resolved_team_id:
            raise RuntimeError(
                "The selected parent issue does not belong to the selected team."
            )

    resolved_assignees = {}
    for index, assignee_id in enumerate(assignee_ids):
        assignee = preflight_data.get(f"targetAssignee{index}")
        if not isinstance(assignee, dict):
            raise RuntimeError(
                f"Linear workspace member {assignee_id!r} was not found."
            )
        resolved_assignees[assignee_id] = assignee

    resolved_labels = {}
    for index, label_id in enumerate(label_ids):
        label = preflight_data.get(f"targetLabel{index}")
        if not isinstance(label, dict):
            raise RuntimeError(f"Linear issue label {label_id!r} was not found.")
        if label.get("archivedAt"):
            raise RuntimeError(
                f"Linear label {str(label.get('name') or label_id)!r} is archived."
            )
        if label.get("isGroup") is True:
            raise RuntimeError(
                f"Linear label {str(label.get('name') or label_id)!r} is a label group."
            )
        label_team = label.get("team")
        label_team_id = (
            str(label_team.get("id") or "")
            if isinstance(label_team, dict)
            else ""
        )
        if label_team_id and label_team_id != resolved_team_id:
            raise RuntimeError(
                f"Linear label {str(label.get('name') or label_id)!r} belongs to another team."
            )
        resolved_labels[label_id] = label

    requested_by_id = {}
    batch_inputs = []
    for issue in issues:
        generated_id = str(uuid.uuid4())
        requested_by_id[generated_id] = issue
        issue_input = {
            "id": generated_id,
            "teamId": resolved_team_id,
            "cycleId": str(cycle.get("id") or cycle_id),
            "title": issue["title"],
        }
        if issue["description"]:
            issue_input["description"] = issue["description"]
        if issue["priority"] is not None:
            issue_input["priority"] = issue["priority"]
        if issue["estimate"] is not None:
            issue_input["estimate"] = issue["estimate"]
        if issue["assignee_id"] is not None:
            issue_input["assigneeId"] = issue["assignee_id"]
        if issue["label_ids"]:
            issue_input["labelIds"] = issue["label_ids"]
        if project_id is not None:
            issue_input["projectId"] = project_id
        if state_id is not None:
            issue_input["stateId"] = state_id
        if parent_issue_id is not None:
            issue_input["parentId"] = str(parent_issue.get("id") or parent_issue_id)
        batch_inputs.append(issue_input)

    write_status, write_data = _graphql(
        """
        mutation RailCallPlanSprint($input: IssueBatchCreateInput!) {
          issueBatchCreate(input: $input) {
            success
            issues {
              id
              identifier
              title
              priority
              estimate
              createdAt
              state { id name type }
              assignee { id name }
              project { id name }
              cycle { id number name }
              parent { id identifier title }
              labels(first: 20) { nodes { id name } }
              team { id name key }
            }
          }
        }
        """,
        {"input": {"issues": batch_inputs}},
        is_write=True,
    )

    payload = write_data.get("issueBatchCreate")
    created = payload.get("issues") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(created, list)
    ):
        raise RuntimeError("Linear did not confirm the sprint issue batch.")
    created = [item for item in created if isinstance(item, dict)]
    if len(created) != len(issues):
        raise RuntimeError(
            "Linear confirmed the sprint batch but returned an unexpected issue "
            "count. Inspect the selected cycle before attempting another plan."
        )

    created_results = []
    mapping_verified = True
    for position, created_issue in enumerate(created, start=1):
        created_id = str(created_issue.get("id") or "")
        requested = requested_by_id.get(created_id)
        if requested is None:
            mapping_verified = False
            requested = issues[position - 1]
        labels_connection = created_issue.get("labels")
        label_nodes = (
            labels_connection.get("nodes")
            if isinstance(labels_connection, dict)
            else []
        )
        if not isinstance(label_nodes, list):
            label_nodes = []
        created_results.append({
            "request_index": requested["request_index"],
            "issue_id": created_id,
            "identifier": str(created_issue.get("identifier") or ""),
            "title": str(created_issue.get("title") or ""),
            "priority": (
                int(created_issue.get("priority"))
                if isinstance(created_issue.get("priority"), (int, float))
                else 0
            ),
            "estimate": (
                int(created_issue.get("estimate"))
                if isinstance(created_issue.get("estimate"), (int, float))
                else 0
            ),
            "state": _entity_summary(created_issue.get("state")),
            "assignee": _entity_summary(created_issue.get("assignee")),
            "project": _entity_summary(created_issue.get("project")),
            "cycle": _entity_summary(created_issue.get("cycle")),
            "parent": (
                {
                    "id": str(created_issue["parent"].get("id") or ""),
                    "identifier": str(
                        created_issue["parent"].get("identifier") or ""
                    ),
                    "title": str(created_issue["parent"].get("title") or ""),
                }
                if isinstance(created_issue.get("parent"), dict)
                else None
            ),
            "labels": [
                _entity_summary(label)
                for label in label_nodes
                if isinstance(label, dict)
            ],
        })
    created_results.sort(key=lambda item: item["request_index"])

    cycle_number = (
        int(cycle.get("number"))
        if isinstance(cycle.get("number"), (int, float))
        else 0
    )
    cycle_name = str(cycle.get("name") or "").strip()
    if not cycle_name:
        cycle_name = f"Cycle {cycle_number}" if cycle_number else "Unnamed cycle"

    blast_radius = {
        "issues_created": len(issues),
        "assignee_links": sum(
            1 for issue in issues if issue["assignee_id"] is not None
        ),
        "label_links": sum(len(issue["label_ids"]) for issue in issues),
        "priority_values": sum(
            1 for issue in issues if issue["priority"] is not None
        ),
        "estimate_values": sum(
            1 for issue in issues if issue["estimate"] is not None
        ),
        "cycle_links": len(issues),
        "project_links": len(issues) if project_id is not None else 0,
        "parent_links": len(issues) if parent_issue_id is not None else 0,
    }

    compact_created = [
        str(item.get("identifier") or "")[:40]
        for item in created_results
    ]
    compact_created_ids = [
        str(item.get("issue_id") or "")
        for item in created_results
    ]
    created_detail_fields = {}
    for slot in range(1, 6):
        if slot <= len(created_results):
            item = created_results[slot - 1]
            title = str(item.get("title") or "")
            detail = {
                "request_index": item.get("request_index"),
                "issue_id": str(item.get("issue_id") or ""),
                "identifier": str(item.get("identifier") or "")[:40],
                "title_preview": title[:48],
                "title_length": len(title),
                "priority": item.get("priority"),
                "estimate": item.get("estimate"),
            }
            detail_text = json.dumps(
                detail,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if len(detail_text) > 280:
                detail["title_preview"] = ""
                detail_text = json.dumps(
                    detail,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            created_detail_fields[f"created_issue_{slot}_json"] = detail_text
        else:
            created_detail_fields[f"created_issue_{slot}_json"] = "null"

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": write_status,
        "preflight_http_status": preflight_status,
        "operation": "plan_sprint",
        "atomic_batch": True,
        "write_request_count": 1,
        "transaction_scope": "Linear issueBatchCreate",
        "team_id": resolved_team_id,
        "team_name": str(team.get("name") or ""),
        "cycle_id": str(cycle.get("id") or ""),
        "cycle_number": cycle_number,
        "cycle_name": cycle_name,
        "project_json": json.dumps(
            _entity_summary(target_project),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "state_json": json.dumps(
            _entity_summary(target_state),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "parent_issue_json": json.dumps(
            (
                {
                    "id": str(parent_issue.get("id") or ""),
                    "identifier": str(parent_issue.get("identifier") or ""),
                    "title": str(parent_issue.get("title") or ""),
                }
                if isinstance(parent_issue, dict)
                else None
            ),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "requested_count": len(issues),
        "created_count": len(created_results),
        "client_id_mapping_verified": mapping_verified,
        "blast_radius_json": json.dumps(
            blast_radius,
            separators=(",", ":"),
        ),
        "created_issues_json": json.dumps(
            compact_created,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "created_issue_ids_json": json.dumps(
            compact_created_ids,
            separators=(",", ":"),
        ),
        **created_detail_fields,
        "completed_steps_json": json.dumps(
            ["preflight", "issue_batch_create"],
            separators=(",", ":"),
        ),
    }, None

def _parse_rebalance_issue_ids_json(value):
    """Parse 2–5 unique Linear issue identifiers for one batch update."""
    if not isinstance(value, str):
        raise RuntimeError("issue_ids_json must be a JSON array string.")
    if len(value) > 2000:
        raise RuntimeError("issue_ids_json must be 2000 characters or fewer.")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "issue_ids_json must be valid JSON containing 2 to 5 issue IDs."
        ) from exc
    if not isinstance(parsed, list):
        raise RuntimeError("issue_ids_json must decode to a JSON array.")
    if len(parsed) < 2 or len(parsed) > 5:
        raise RuntimeError("issue_ids_json must contain between 2 and 5 issues.")

    result = []
    seen = set()
    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, str) or not item.strip():
            raise RuntimeError(
                f"issue_ids_json item {index} must be a non-empty issue UUID or identifier."
            )
        item = item.strip()
        if len(item) > 200:
            raise RuntimeError("Issue IDs must be 200 characters or fewer.")
        key = item.casefold()
        if key in seen:
            raise RuntimeError("issue_ids_json must not contain duplicate issues.")
        seen.add(key)
        result.append(item)
    return result


def linear_rebalance_sprint(inputs, stamp):
    """Apply one bounded shared update to 2–5 issues in one batch request."""
    requested_issue_ids = _parse_rebalance_issue_ids_json(
        inputs.get("issue_ids_json")
    )

    state_id = _optional_linear_id(
        inputs,
        "state_id",
        "Linear workflow-state UUID",
    )
    assignee_id = _optional_linear_id(
        inputs,
        "assignee_id",
        "Linear workspace-member UUID",
    )
    project_id = _optional_linear_id(
        inputs,
        "project_id",
        "Linear project UUID",
    )
    cycle_id = _optional_linear_id(
        inputs,
        "cycle_id",
        "Linear cycle UUID",
    )

    clear_assignee = _optional_boolean(inputs, "clear_assignee")
    clear_project = _optional_boolean(inputs, "clear_project")
    clear_cycle = _optional_boolean(inputs, "clear_cycle")

    if assignee_id is not None and clear_assignee:
        raise RuntimeError("Supply assignee_id or clear_assignee=true, not both.")
    if project_id is not None and clear_project:
        raise RuntimeError("Supply project_id or clear_project=true, not both.")
    if cycle_id is not None and clear_cycle:
        raise RuntimeError("Supply cycle_id or clear_cycle=true, not both.")

    priority = None
    if "priority" in inputs:
        raw_priority = inputs.get("priority")
        if isinstance(raw_priority, bool):
            raise RuntimeError("priority must be an integer from 0 to 4.")
        try:
            priority = int(raw_priority)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("priority must be an integer from 0 to 4.") from exc
        if priority < 0 or priority > 4:
            raise RuntimeError("priority must be between 0 and 4.")

    estimate = None
    if "estimate" in inputs:
        raw_estimate = inputs.get("estimate")
        if isinstance(raw_estimate, bool):
            raise RuntimeError("estimate must be an integer from 0 to 100.")
        try:
            estimate = int(raw_estimate)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("estimate must be an integer from 0 to 100.") from exc
        if estimate < 0 or estimate > 100:
            raise RuntimeError("estimate must be between 0 and 100.")

    label_ids = None
    if "label_ids_json" in inputs:
        label_ids = _parse_label_ids_json(inputs.get("label_ids_json"))

    requested_fields = []
    if priority is not None:
        requested_fields.append("priority")
    if estimate is not None:
        requested_fields.append("estimate")
    if state_id is not None:
        requested_fields.append("state")
    if assignee_id is not None or clear_assignee:
        requested_fields.append("assignee")
    if project_id is not None or clear_project:
        requested_fields.append("project")
    if cycle_id is not None or clear_cycle:
        requested_fields.append("cycle")
    if label_ids is not None:
        requested_fields.append("labels")
    if not requested_fields:
        raise RuntimeError(
            "Supply at least one shared sprint change: priority, estimate, "
            "state_id, assignee_id/clear_assignee, project_id/clear_project, "
            "cycle_id/clear_cycle, or label_ids_json."
        )

    variable_definitions = []
    query_fields = []
    variables = {}
    for index, issue_id in enumerate(requested_issue_ids):
        variable_name = f"issueId{index}"
        variable_definitions.append(f"${variable_name}: String!")
        query_fields.append(
            f"issue{index}: issue(id: ${variable_name}) {{ "
            "id identifier title archivedAt priority estimate "
            "state { id name type team { id name } } "
            "assignee { id name } "
            "project { id name archivedAt } "
            "cycle { id number name completedAt team { id name } } "
            "labels(first: 20) { nodes { id name isGroup archivedAt team { id name } } } "
            "team { id name key } }"
        )
        variables[variable_name] = issue_id

    if state_id is not None:
        variable_definitions.append("$stateId: String!")
        query_fields.append(
            "targetState: workflowState(id: $stateId) { "
            "id name type archivedAt team { id name } }"
        )
        variables["stateId"] = state_id
    if assignee_id is not None:
        variable_definitions.append("$assigneeId: String!")
        query_fields.append(
            "targetAssignee: user(id: $assigneeId) { id name }"
        )
        variables["assigneeId"] = assignee_id
    if project_id is not None:
        variable_definitions.append("$projectId: String!")
        query_fields.append(
            "targetProject: project(id: $projectId) { id name archivedAt teamIds }"
        )
        variables["projectId"] = project_id
    if cycle_id is not None:
        variable_definitions.append("$cycleId: String!")
        query_fields.append(
            "targetCycle: cycle(id: $cycleId) { "
            "id number name completedAt team { id name } }"
        )
        variables["cycleId"] = cycle_id
    for index, label_id in enumerate(label_ids or []):
        variable_name = f"labelId{index}"
        variable_definitions.append(f"${variable_name}: String!")
        query_fields.append(
            f"targetLabel{index}: issueLabel(id: ${variable_name}) {{ "
            "id name isGroup archivedAt team { id name } }"
        )
        variables[variable_name] = label_id

    preflight_status, preflight_data = _graphql(
        "query RailCallRebalanceSprintPreflight("
        + ", ".join(variable_definitions)
        + ") {\n"
        + "\n".join(query_fields)
        + "\n}",
        variables,
    )

    issues = []
    team_id = ""
    team_name = ""
    for index, supplied_id in enumerate(requested_issue_ids):
        issue = preflight_data.get(f"issue{index}")
        if not isinstance(issue, dict):
            raise RuntimeError(f"Linear issue {supplied_id!r} was not found.")
        if issue.get("archivedAt"):
            raise RuntimeError(
                f"Linear issue {str(issue.get('identifier') or supplied_id)!r} is archived."
            )
        issue_team = issue.get("team")
        issue_team_id = (
            str(issue_team.get("id") or "")
            if isinstance(issue_team, dict)
            else ""
        )
        if not issue_team_id:
            raise RuntimeError("Linear did not return the issue team during preflight.")
        if not team_id:
            team_id = issue_team_id
            team_name = str(issue_team.get("name") or "")
        elif issue_team_id != team_id:
            raise RuntimeError(
                "All issues in one sprint rebalance must belong to the same team."
            )
        issues.append(issue)

    target_state = preflight_data.get("targetState")
    if state_id is not None:
        if not isinstance(target_state, dict):
            raise RuntimeError(f"Linear workflow state {state_id!r} was not found.")
        if target_state.get("archivedAt"):
            raise RuntimeError("The selected workflow state is archived.")
        target_team = target_state.get("team")
        target_team_id = (
            str(target_team.get("id") or "")
            if isinstance(target_team, dict)
            else ""
        )
        if target_team_id != team_id:
            raise RuntimeError(
                "The selected workflow state does not belong to the issues' team."
            )

    target_assignee = preflight_data.get("targetAssignee")
    if assignee_id is not None and not isinstance(target_assignee, dict):
        raise RuntimeError(f"Linear workspace member {assignee_id!r} was not found.")

    target_project = preflight_data.get("targetProject")
    if project_id is not None:
        if not isinstance(target_project, dict):
            raise RuntimeError(f"Linear project {project_id!r} was not found.")
        if target_project.get("archivedAt"):
            raise RuntimeError("The selected project is archived.")
        project_team_ids = target_project.get("teamIds")
        if not isinstance(project_team_ids, list) or team_id not in {
            str(item) for item in project_team_ids
        }:
            raise RuntimeError(
                "The selected project is not associated with the issues' team."
            )

    target_cycle = preflight_data.get("targetCycle")
    if cycle_id is not None:
        if not isinstance(target_cycle, dict):
            raise RuntimeError(f"Linear cycle {cycle_id!r} was not found.")
        target_team = target_cycle.get("team")
        target_team_id = (
            str(target_team.get("id") or "")
            if isinstance(target_team, dict)
            else ""
        )
        if target_team_id != team_id:
            raise RuntimeError(
                "The selected cycle does not belong to the issues' team."
            )
        if target_cycle.get("completedAt"):
            raise RuntimeError("The selected cycle is already completed.")

    target_labels = []
    if label_ids is not None:
        for index, label_id in enumerate(label_ids):
            label = preflight_data.get(f"targetLabel{index}")
            if not isinstance(label, dict):
                raise RuntimeError(f"Linear issue label {label_id!r} was not found.")
            if label.get("archivedAt"):
                raise RuntimeError(
                    f"The selected label {str(label.get('name') or label_id)!r} is archived."
                )
            if label.get("isGroup") is True:
                raise RuntimeError(
                    f"The selected label {str(label.get('name') or label_id)!r} is a label group."
                )
            label_team = label.get("team")
            label_team_id = (
                str(label_team.get("id") or "")
                if isinstance(label_team, dict)
                else ""
            )
            if label_team_id and label_team_id != team_id:
                raise RuntimeError(
                    f"The selected label {str(label.get('name') or label_id)!r} belongs to another team."
                )
            target_labels.append(label)

    update_input = {}
    if priority is not None:
        update_input["priority"] = priority
    if estimate is not None:
        update_input["estimate"] = estimate
    if state_id is not None:
        update_input["stateId"] = state_id
    if clear_assignee:
        update_input["assigneeId"] = None
    elif assignee_id is not None:
        update_input["assigneeId"] = assignee_id
    if clear_project:
        update_input["projectId"] = None
    elif project_id is not None:
        update_input["projectId"] = project_id
    if clear_cycle:
        update_input["cycleId"] = None
    elif cycle_id is not None:
        update_input["cycleId"] = cycle_id
    if label_ids is not None:
        update_input["labelIds"] = label_ids

    changed_issue_count = 0
    for issue in issues:
        differs = False
        if priority is not None:
            current = issue.get("priority")
            current = int(current) if isinstance(current, (int, float)) else 0
            differs = differs or current != priority
        if estimate is not None:
            current = issue.get("estimate")
            current = int(current) if isinstance(current, (int, float)) else 0
            differs = differs or current != estimate
        if state_id is not None:
            current = issue.get("state")
            current_id = str(current.get("id") or "") if isinstance(current, dict) else ""
            differs = differs or current_id != state_id
        if assignee_id is not None or clear_assignee:
            current = issue.get("assignee")
            current_id = str(current.get("id") or "") if isinstance(current, dict) else ""
            desired = assignee_id or ""
            differs = differs or current_id != desired
        if project_id is not None or clear_project:
            current = issue.get("project")
            current_id = str(current.get("id") or "") if isinstance(current, dict) else ""
            desired = project_id or ""
            differs = differs or current_id != desired
        if cycle_id is not None or clear_cycle:
            current = issue.get("cycle")
            current_id = str(current.get("id") or "") if isinstance(current, dict) else ""
            desired = cycle_id or ""
            differs = differs or current_id != desired
        if label_ids is not None:
            connection = issue.get("labels")
            nodes = connection.get("nodes") if isinstance(connection, dict) else []
            if not isinstance(nodes, list):
                nodes = []
            current_ids = {
                str(label.get("id") or "")
                for label in nodes
                if isinstance(label, dict) and str(label.get("id") or "")
            }
            differs = differs or current_ids != set(label_ids)
        if differs:
            changed_issue_count += 1

    if changed_issue_count == 0:
        raise RuntimeError(
            "The requested shared properties already match every issue. "
            "No Linear write was attempted."
        )

    resolved_ids = [str(issue.get("id") or "") for issue in issues]
    if any(not value for value in resolved_ids):
        raise RuntimeError("Linear did not return every issue UUID during preflight.")

    write_status, write_data = _graphql(
        """
        mutation RailCallRebalanceSprint(
          $ids: [UUID!]!
          $input: IssueUpdateInput!
        ) {
          issueBatchUpdate(ids: $ids, input: $input) {
            success
            issues {
              id
              identifier
              title
              priority
              estimate
              updatedAt
              state { id name type }
              assignee { id name }
              project { id name }
              cycle { id number name }
              labels(first: 20) { nodes { id name } }
              team { id name key }
            }
          }
        }
        """,
        {"ids": resolved_ids, "input": update_input},
        is_write=True,
    )

    payload = write_data.get("issueBatchUpdate")
    updated = payload.get("issues") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or not isinstance(updated, list)
    ):
        raise RuntimeError("Linear did not confirm the sprint rebalance batch.")
    updated = [item for item in updated if isinstance(item, dict)]
    if len(updated) != len(issues):
        raise RuntimeError(
            "Linear confirmed the batch update but returned an unexpected issue "
            "count. Inspect the selected issues before retrying."
        )
    returned_ids = {str(issue.get("id") or "") for issue in updated}
    if returned_ids != set(resolved_ids):
        raise RuntimeError(
            "Linear returned a different issue set after the batch update. "
            "Inspect the selected issues before retrying."
        )

    updated.sort(key=lambda item: resolved_ids.index(str(item.get("id") or "")))
    identifiers = [str(item.get("identifier") or "")[:40] for item in updated]
    detail_fields = {}
    for slot in range(1, 6):
        if slot <= len(updated):
            item = updated[slot - 1]
            state = item.get("state")
            assignee = item.get("assignee")
            cycle = item.get("cycle")
            title = str(item.get("title") or "")
            detail = {
                "request_index": slot,
                "issue_id": str(item.get("id") or ""),
                "identifier": str(item.get("identifier") or "")[:40],
                "title_preview": title[:40],
                "priority": (
                    int(item.get("priority"))
                    if isinstance(item.get("priority"), (int, float))
                    else 0
                ),
                "estimate": (
                    int(item.get("estimate"))
                    if isinstance(item.get("estimate"), (int, float))
                    else 0
                ),
                "state": str(state.get("name") or "")[:30] if isinstance(state, dict) else "",
                "assignee": str(assignee.get("name") or "")[:30] if isinstance(assignee, dict) else "",
                "cycle": str(cycle.get("number") or "") if isinstance(cycle, dict) else "",
            }
            detail_text = json.dumps(detail, ensure_ascii=False, separators=(",", ":"))
            if len(detail_text) > 280:
                detail["title_preview"] = ""
                detail["state"] = ""
                detail["assignee"] = ""
                detail_text = json.dumps(detail, ensure_ascii=False, separators=(",", ":"))
            detail_fields[f"updated_issue_{slot}_json"] = detail_text
        else:
            detail_fields[f"updated_issue_{slot}_json"] = "null"

    blast_radius = {
        "issues_targeted": len(issues),
        "issues_with_detected_change": changed_issue_count,
        "shared_fields": len(requested_fields),
        "label_replacement_count": len(label_ids or []),
        "write_requests": 1,
    }

    return {
        "ok": True,
        "loaded_from": "module:muhammad-akif-janjua/linear-guard",
        "http_status": write_status,
        "preflight_http_status": preflight_status,
        "operation": "rebalance_sprint",
        "batch_update": True,
        "write_request_count": 1,
        "batch_scope": "Linear issueBatchUpdate",
        "team_id": team_id,
        "team_name": team_name,
        "requested_count": len(issues),
        "updated_count": len(updated),
        "changed_issue_count": changed_issue_count,
        "changes_requested_json": json.dumps(
            requested_fields,
            separators=(",", ":"),
        ),
        "blast_radius_json": json.dumps(
            blast_radius,
            separators=(",", ":"),
        ),
        "updated_issues_json": json.dumps(
            identifiers,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "updated_issue_ids_json": json.dumps(
            resolved_ids,
            separators=(",", ":"),
        ),
        **detail_fields,
        "completed_steps_json": json.dumps(
            ["preflight", "issue_batch_update"],
            separators=(",", ":"),
        ),
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
