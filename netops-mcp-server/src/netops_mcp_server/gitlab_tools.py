"""
Copyright (c) 2026 Cisco and/or its affiliates.

This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.1 (the "License"). You may obtain a copy of the
License at

               https://developer.cisco.com/docs/licenses

All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by the License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied.

---
GitLab tools for CI/CD: trigger pipeline, status, logs, artifacts, repo file read/update.
"""
import base64
import logging
import os
import re
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Union

import httpx

logger = logging.getLogger(__name__)

GITLAB_URL = os.getenv("GITLAB_URL", "https://gitlab.com").rstrip("/")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", "")
GITLAB_DEFAULT_PROJECT_ID = os.getenv("GITLAB_DEFAULT_PROJECT_ID", "")
DEFAULT_ALLOWED_VARS = [
    "DRY_RUN", "TARGET_HOST", "TARGET_HOSTS", "SITE_PIPELINE", "SWITCH_PIPELINE",
    "PLAYBOOK", "EXTRA_VARS", "LIMIT", "TAGS", "SKIP_TAGS", "VERBOSITY",
    "DRY_RUN_PIPELINE", "COLLECT_PIPELINE", "COMPARE_ONLY", "ROLLBACK_PIPELINE", "PIPELINE_TYPE",
    "COMMIT_COLLECTED", "COMMIT_DIFFS",
]
GITLAB_ALLOWED_VARIABLES = [v.strip() for v in os.getenv("GITLAB_ALLOWED_VARIABLES", ",".join(DEFAULT_ALLOWED_VARS)).split(",") if v.strip()]
DEFAULT_ALLOWED_PATHS = ["ansible/", "host_vars/", "group_vars/", "configs/", "templates/", "inventory/", "playbooks/", "roles/", "vars/"]
GITLAB_ALLOWED_FILE_PATHS = os.getenv("GITLAB_ALLOWED_FILE_PATHS", ",".join(DEFAULT_ALLOWED_PATHS)).split(",")
BLOCKED_PATTERNS = [r"\.gitlab-ci\.yml$", r"\.env", r"secrets?", r"\.git/", r"Dockerfile", r"\.ssh/", r"id_rsa", r"\.pem$", r"\.key$"]
RATE_LIMIT_TRIGGER = int(os.getenv("GITLAB_RATE_LIMIT_TRIGGER", "10"))
RATE_LIMIT_FILE = int(os.getenv("GITLAB_RATE_LIMIT_FILE_UPDATE", "30"))
_rate: Dict[str, List[float]] = defaultdict(list)


def _check_rate(operation: str, limit: int) -> Optional[str]:
    now = time.time()
    key = operation
    _rate[key] = [t for t in _rate[key] if now - t < 60]
    if len(_rate[key]) >= limit:
        return f"Rate limit exceeded for {operation} (max {limit}/min)"
    _rate[key].append(now)
    return None


def _req(method: str, path: str, params: Optional[Dict] = None, json_data: Optional[Dict] = None, raw_response: bool = False) -> Dict[str, Any]:
    url = f"{GITLAB_URL}/api/v4/{path}"
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN, "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=30.0) as client:
            if method == "GET":
                r = client.get(url, headers=headers, params=params)
            elif method == "POST":
                r = client.post(url, headers=headers, json=json_data)
            elif method == "PUT":
                r = client.put(url, headers=headers, json=json_data)
            else:
                return {"success": False, "error": f"Unsupported method {method}"}
            r.raise_for_status()
            if raw_response:
                return {"success": True, "data": r.text}
            return {"success": True, "data": r.json() if r.content else None}
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _validate_path(file_path: str) -> Optional[str]:
    if not file_path or ".." in file_path:
        return "Invalid file path"
    allowed = any(file_path.startswith(p.strip()) for p in GITLAB_ALLOWED_FILE_PATHS if p.strip())
    if not allowed:
        return f"Path not in allowlist. Allowed prefixes: {GITLAB_ALLOWED_FILE_PATHS}"
    for pat in BLOCKED_PATTERNS:
        if re.search(pat, file_path):
            return f"Path matches blocked pattern: {pat}"
    return None


def _encode_path(p: str) -> str:
    return p.replace("/", "%2F").replace(".", "%2E")


def _norm_project_id(project_id: Optional[Union[str, int]]) -> Optional[str]:
    """Normalize project_id so API callers can pass int (e.g. from list_gitlab_projects) or str."""
    if project_id is None:
        return None
    return str(project_id).strip() or None


def _filter_vars(variables: Dict[str, str]) -> Dict[str, str]:
    allowed = set(GITLAB_ALLOWED_VARIABLES)
    return {k: v for k, v in variables.items() if k.strip() in allowed}


def trigger_gitlab_pipeline(
    project_id: Optional[Union[str, int]] = None,
    ref: str = "main",
    variables: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Trigger a CI/CD pipeline in GitLab via POST projects/:id/pipeline (same as Run pipeline in UI).
    Uses GITLAB_TOKEN; variables are sent in the JSON body. project_id can be numeric or string."""
    err = _check_rate("trigger", RATE_LIMIT_TRIGGER)
    if err:
        return {"success": False, "error": err}
    if not GITLAB_TOKEN:
        return {"success": False, "error": "GITLAB_TOKEN is required for pipeline triggers"}
    project = _norm_project_id(project_id) or GITLAB_DEFAULT_PROJECT_ID
    if not project:
        return {"success": False, "error": "project_id required (no default configured)"}
    raw_vars = variables or {}
    filtered = _filter_vars(raw_vars)
    if raw_vars and not filtered:
        allow_preview = GITLAB_ALLOWED_VARIABLES[:10] if len(GITLAB_ALLOWED_VARIABLES) > 10 else GITLAB_ALLOWED_VARIABLES
        logger.warning(
            "gitlab trigger: all variables were filtered out. input_keys=%s allowlist_len=%s allowlist_preview=%s (set GITLAB_ALLOWED_VARIABLES to include COMPARE_ONLY, PIPELINE_TYPE, COLLECT_PIPELINE, etc.)",
            list(raw_vars.keys()),
            len(GITLAB_ALLOWED_VARIABLES),
            allow_preview,
        )
    logger.info(
        "gitlab trigger: project=%s ref=%s variables_keys=%s",
        project,
        ref,
        list(filtered.keys()) if filtered else [],
    )
    data: Dict[str, Any] = {"ref": ref}
    if filtered:
        data["variables"] = [{"key": k, "value": v} for k, v in filtered.items()]
    logger.debug("gitlab trigger: path=projects/%s/pipeline data_keys=%s", _encode_path(project), list(data.keys()))
    result = _req("POST", f"projects/{_encode_path(project)}/pipeline", json_data=data)
    if not result["success"]:
        logger.warning("gitlab trigger api failed: error=%s", result.get("error", "")[:300])
        return result
    p = result["data"]
    logger.info("gitlab trigger success: pipeline_id=%s", p.get("id"))
    return {"success": True, "pipeline_id": p.get("id"), "web_url": p.get("web_url"), "status": p.get("status"), "ref": p.get("ref")}


def get_gitlab_pipeline_status(project_id: Optional[Union[str, int]] = None, pipeline_id: int = 0) -> Dict[str, Any]:
    """Get the status of a GitLab pipeline."""
    project = _norm_project_id(project_id) or GITLAB_DEFAULT_PROJECT_ID
    if not project or not pipeline_id:
        return {"success": False, "error": "project_id and pipeline_id required"}
    result = _req("GET", f"projects/{_encode_path(project)}/pipelines/{pipeline_id}")
    if not result["success"]:
        return result
    p = result["data"]
    jobs_r = _req("GET", f"projects/{_encode_path(project)}/pipelines/{pipeline_id}/jobs")
    jobs = []
    if jobs_r["success"] and jobs_r.get("data"):
        jobs = [{"id": j.get("id"), "name": j.get("name"), "status": j.get("status"), "stage": j.get("stage")} for j in jobs_r["data"]]
    return {"success": True, "pipeline_id": p.get("id"), "status": p.get("status"), "web_url": p.get("web_url"), "jobs": jobs}


def get_gitlab_job_logs(project_id: Optional[Union[str, int]] = None, job_id: int = 0) -> Dict[str, Any]:
    """Get logs for a GitLab job (trace is plain text, not JSON)."""
    project = _norm_project_id(project_id) or GITLAB_DEFAULT_PROJECT_ID
    if not project or not job_id:
        return {"success": False, "error": "project_id and job_id required"}
    result = _req("GET", f"projects/{_encode_path(project)}/jobs/{job_id}/trace", raw_response=True)
    if not result["success"]:
        return result
    logs = result.get("data") or ""
    if not isinstance(logs, str):
        logs = str(logs)
    return {"success": True, "job_id": job_id, "logs": logs[:50000], "truncated": len(logs) > 50000}


def get_gitlab_job_artifact(
    project_id: Optional[Union[str, int]] = None,
    job_id: int = 0,
    artifact_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Get artifact content from a GitLab job, or list artifacts."""
    project = _norm_project_id(project_id) or GITLAB_DEFAULT_PROJECT_ID
    if not project or not job_id:
        return {"success": False, "error": "project_id and job_id required"}
    if artifact_path:
        # GitLab API: GET /projects/:id/jobs/:job_id/artifacts/*artifact_path (path as segments, not encoded)
        result = _req("GET", f"projects/{_encode_path(project)}/jobs/{job_id}/artifacts/{artifact_path}", raw_response=True)
        if not result["success"]:
            return result
        return {"success": True, "job_id": job_id, "artifact_path": artifact_path, "content": result["data"]}
    result = _req("GET", f"projects/{_encode_path(project)}/jobs/{job_id}")
    if not result["success"]:
        return result
    job = result["data"]
    return {"success": True, "job_id": job_id, "artifacts": job.get("artifacts", []), "message": "Specify artifact_path to download"}


def play_gitlab_job(
    project_id: Optional[Union[str, int]] = None,
    job_id: int = 0,
) -> Dict[str, Any]:
    """Play (trigger) a manual GitLab job. Use after triggering a pipeline that has manual jobs (e.g. rollback_apply)."""
    project = _norm_project_id(project_id) or GITLAB_DEFAULT_PROJECT_ID
    if not project or not job_id:
        return {"success": False, "error": "project_id and job_id required"}
    result = _req("POST", f"projects/{_encode_path(project)}/jobs/{job_id}/play", json_data={})
    if not result["success"]:
        return result
    job = result.get("data") or {}
    return {
        "success": True,
        "job_id": job_id,
        "name": job.get("name"),
        "status": job.get("status"),
        "message": "Manual job started.",
    }


def list_gitlab_projects(search: Optional[str] = None, per_page: int = 20) -> Dict[str, Any]:
    """List GitLab projects accessible with the token."""
    params = {"per_page": min(per_page, 100), "order_by": "last_activity_at", "sort": "desc"}
    if search:
        params["search"] = search
    result = _req("GET", "projects", params=params)
    if not result["success"]:
        return result
    projects = [{"id": p.get("id"), "path_with_namespace": p.get("path_with_namespace"), "name": p.get("name"), "web_url": p.get("web_url")} for p in result["data"]]
    return {"success": True, "count": len(projects), "projects": projects}


def list_gitlab_pipelines(project_id: Optional[Union[str, int]] = None, per_page: int = 10, status: Optional[str] = None) -> Dict[str, Any]:
    """List recent pipelines for a project."""
    project = _norm_project_id(project_id) or GITLAB_DEFAULT_PROJECT_ID
    if not project:
        return {"success": False, "error": "project_id required"}
    params = {"per_page": min(per_page, 100)}
    if status:
        params["status"] = status
    result = _req("GET", f"projects/{_encode_path(project)}/pipelines", params=params)
    if not result["success"]:
        return result
    pipelines = [{"id": p.get("id"), "status": p.get("status"), "ref": p.get("ref"), "web_url": p.get("web_url")} for p in result["data"]]
    return {"success": True, "count": len(pipelines), "pipelines": pipelines}


def get_gitlab_repository_file(
    project_id: Optional[Union[str, int]] = None,
    file_path: str = "",
    ref: str = "main",
) -> Dict[str, Any]:
    """Get content of a file from a GitLab repository (allowed paths only)."""
    project = _norm_project_id(project_id) or GITLAB_DEFAULT_PROJECT_ID
    if not project or not file_path:
        return {"success": False, "error": "project_id and file_path required"}
    path_err = _validate_path(file_path)
    if path_err:
        return {"success": False, "error": path_err}
    enc = _encode_path(file_path)
    result = _req("GET", f"projects/{_encode_path(project)}/repository/files/{enc}", params={"ref": ref})
    if not result["success"]:
        return result
    fd = result["data"]
    content = fd.get("content", "")
    if fd.get("encoding") == "base64":
        try:
            content = base64.b64decode(content).decode("utf-8")
        except Exception:
            content = "[Binary - cannot decode]"
    return {"success": True, "file_path": file_path, "ref": ref, "content": content}


def update_gitlab_repository_file(
    project_id: Optional[Union[str, int]] = None,
    file_path: str = "",
    content: str = "",
    branch: str = "main",
    commit_message: str = "",
) -> Dict[str, Any]:
    """Create or update a file in a GitLab repository (allowed paths, rate limited).
    If the file does not exist, uses GitLab create (POST); otherwise update (PUT).
    Use this for ansible/configs/desired/<host>.txt when the file may not exist yet."""
    err = _check_rate("file_update", RATE_LIMIT_FILE)
    if err:
        return {"success": False, "error": err}
    project = _norm_project_id(project_id) or GITLAB_DEFAULT_PROJECT_ID
    if not project or not file_path:
        return {"success": False, "error": "project_id and file_path required"}
    path_err = _validate_path(file_path)
    if path_err:
        return {"success": False, "error": path_err}
    if not commit_message:
        commit_message = f"Update {file_path}"
    import base64 as b64
    encoded = b64.b64encode(content.encode("utf-8")).decode("ascii")
    body = {"branch": branch, "content": encoded, "commit_message": commit_message, "encoding": "base64"}
    enc = _encode_path(file_path)
    base = f"projects/{_encode_path(project)}/repository/files/{enc}"

    # Check if file exists: GET with ref=branch
    get_result = _req("GET", base, params={"ref": branch})
    if get_result["success"]:
        # File exists → update (PUT)
        result = _req("PUT", base, json_data=body)
    else:
        err_msg = (get_result.get("error") or "").lower()
        if "404" in str(get_result.get("error", "")) or "doesn't exist" in err_msg:
            # File does not exist → create (POST)
            result = _req("POST", base, json_data=body)
        else:
            return get_result

    if not result["success"]:
        return result
    data = result.get("data") or {}
    return {"success": True, "file_path": file_path, "branch": branch, "commit_id": data.get("last_commit_id") or data.get("file_path")}


GITLAB_TOOLS = [
    (trigger_gitlab_pipeline, "trigger_gitlab_pipeline"),
    (get_gitlab_pipeline_status, "get_gitlab_pipeline_status"),
    (get_gitlab_job_logs, "get_gitlab_job_logs"),
    (get_gitlab_job_artifact, "get_gitlab_job_artifact"),
    (play_gitlab_job, "play_gitlab_job"),
    (list_gitlab_projects, "list_gitlab_projects"),
    (list_gitlab_pipelines, "list_gitlab_pipelines"),
    (get_gitlab_repository_file, "get_gitlab_repository_file"),
    (update_gitlab_repository_file, "update_gitlab_repository_file"),
]
