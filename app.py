
import os
import re
import hmac
import requests

from flask import Flask, jsonify, request

app = Flask(__name__)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

GITHUB_API = "https://api.github.com"
REQUIREMENTS_FOLDER = "requirements"

SUBJECTS = [
    "Earth Science 1",
    "Biology 1",
    "Chemistry 1",
    "Physics 1",
    "Mathematics 2A",
    "Mathematics 2B",
    "Computer Science 2",
    "ADTech 2",
    "English 2",
    "Filipino 2",
    "Social Science 2",
    "Values Education 2",
    "Physical Education 2",
    "Health 2",
    "Music 2",
]


def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_url(path):
    return f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}"


def validate_configuration():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False
    if "/" not in GITHUB_REPO:
        return False
    return True


def safe_filename(label):
    """Convert a requirement label into a safe filename."""
    label = label.strip()

    if not label or len(label) > 100:
        return None

    # Keep letters, numbers, spaces, underscores, and hyphens.
    if not re.fullmatch(r"[\w -]+", label, flags=re.UNICODE):
        return None

    slug = re.sub(r"\s+", "-", label)
    slug = re.sub(r"-+", "-", slug).strip("-")

    if not slug:
        return None

    return f"{slug}.json"


def get_file(path):
    response = requests.get(
        github_url(path),
        headers=github_headers(),
        params={"ref": GITHUB_BRANCH},
        timeout=20,
    )

    if response.status_code == 404:
        return None, None

    if not response.ok:
        raise RuntimeError(
            f"GitHub returned HTTP {response.status_code}"
        )

    data = response.json()
    return data, data.get("sha")


@app.after_request
def add_cors_headers(response):
    # This API uses no browser cookies. Admin requests use a password
    # in the Authorization header instead.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization"
    )
    response.headers["Access-Control-Allow-Methods"] = (
        "GET, POST, DELETE, OPTIONS"
    )
    return response


@app.get("/")
def home():
    return jsonify({
        "status": "online",
        "service": "PSHS Requirements Backend",
    })


@app.get("/health")
def health():
    return jsonify({"status": "healthy"}), 200


@app.get("/subjects")
def get_subjects():
    return jsonify({"subjects": SUBJECTS})


@app.post("/submit")
def submit_requirement():
    if not validate_configuration():
        return jsonify({"error": "Backend GitHub configuration is missing."}), 500

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Send the submission as JSON."}), 400

    subject = data.get("subject")
    label = data.get("label")
    details = data.get("details", "")
    due_date = data.get("dueDate", "")

    if subject not in SUBJECTS:
        return jsonify({"error": "Please select a valid subject."}), 400

    if not isinstance(label, str):
        return jsonify({"error": "Requirement label is required."}), 400

    filename = safe_filename(label)

    if filename is None:
        return jsonify({
            "error": (
                "The label must be 1–100 characters and contain only "
                "letters, numbers, spaces, underscores, or hyphens."
            )
        }), 400

    if not isinstance(details, str) or len(details) > 5000:
        return jsonify({"error": "Details must be text under 5000 characters."}), 400

    if not isinstance(due_date, str) or len(due_date) > 50:
        return jsonify({"error": "Invalid due date."}), 400

    path = f"{REQUIREMENTS_FOLDER}/{subject}/{filename}"

    try:
        existing, _ = get_file(path)

        if existing is not None:
            return jsonify({
                "error": "A requirement with this label already exists in this subject."
            }), 409

        content = {
            "subject": subject,
            "label": label.strip(),
            "details": details.strip(),
            "dueDate": due_date.strip(),
        }

        import json
        import base64

        encoded = base64.b64encode(
            json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("utf-8")

        response = requests.put(
            github_url(path),
            headers=github_headers(),
            json={
                "message": f"Add requirement: {label.strip()} ({subject})",
                "content": encoded,
                "branch": GITHUB_BRANCH,
            },
            timeout=30,
        )

        if response.status_code not in (200, 201):
            app.logger.error(
                "GitHub submission failed: HTTP %s", response.status_code
            )
            return jsonify({"error": "GitHub could not save the submission."}), 502

        return jsonify({
            "success": True,
            "message": "Requirement submitted successfully.",
            "subject": subject,
            "label": label.strip(),
        }), 201

    except requests.RequestException:
        app.logger.exception("Network error while submitting requirement")
        return jsonify({"error": "Could not connect to GitHub. Try again later."}), 502
    except RuntimeError:
        app.logger.exception("GitHub API error during submission")
        return jsonify({"error": "GitHub could not process the submission."}), 502


@app.get("/requirements")
def list_requirements():
    """Return saved requirement JSON files grouped by subject."""
    if not validate_configuration():
        return jsonify({"error": "Backend GitHub configuration is missing."}), 500

    results = {subject: [] for subject in SUBJECTS}

    try:
        for subject in SUBJECTS:
            folder = f"{REQUIREMENTS_FOLDER}/{subject}"
            response = requests.get(
                github_url(folder),
                headers=github_headers(),
                params={"ref": GITHUB_BRANCH},
                timeout=20,
            )

            if response.status_code == 404:
                continue

            if not response.ok:
                app.logger.error(
                    "GitHub listing failed: HTTP %s", response.status_code
                )
                return jsonify({"error": "Could not load requirements."}), 502

            files = response.json()

            if not isinstance(files, list):
                continue

            for file_info in files:
                if file_info.get("type") != "file":
                    continue
                if not file_info.get("name", "").endswith(".json"):
                    continue

                file_response = requests.get(
                    file_info["url"],
                    headers=github_headers(),
                    params={"ref": GITHUB_BRANCH},
                    timeout=20,
                )

                if not file_response.ok:
                    continue

                import base64
                import json

                file_data = file_response.json()
                raw = base64.b64decode(file_data["content"]).decode("utf-8")
                requirement = json.loads(raw)
                requirement["filename"] = file_info["name"]
                results[subject].append(requirement)

        return jsonify({"requirements": results})

    except (requests.RequestException, RuntimeError, ValueError, KeyError):
        app.logger.exception("Could not load requirements")
        return jsonify({"error": "Could not load requirements."}), 502


@app.delete("/delete")
def delete_requirement():
    if not validate_configuration():
        return jsonify({"error": "Backend GitHub configuration is missing."}), 500

    if not ADMIN_PASSWORD:
        return jsonify({"error": "Admin password is not configured."}), 500

    provided_password = request.headers.get("Authorization", "")
    if provided_password.startswith("Bearer "):
        provided_password = provided_password[7:]

    if not hmac.compare_digest(provided_password, ADMIN_PASSWORD):
        return jsonify({"error": "Unauthorized."}), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Send the deletion request as JSON."}), 400

    subject = data.get("subject")
    filename = data.get("filename")

    if subject not in SUBJECTS:
        return jsonify({"error": "Invalid subject."}), 400

    if not isinstance(filename, str) or not re.fullmatch(
        r"[\w -]+\.json", filename, flags=re.UNICODE
    ):
        return jsonify({"error": "Invalid filename."}), 400

    path = f"{REQUIREMENTS_FOLDER}/{subject}/{filename}"

    try:
        file_data, sha = get_file(path)

        if file_data is None:
            return jsonify({"error": "Requirement not found."}), 404

        response = requests.delete(
            github_url(path),
            headers=github_headers(),
            json={
                "message": f"Delete requirement: {filename} ({subject})",
                "sha": sha,
                "branch": GITHUB_BRANCH,
            },
            timeout=30,
        )

        if response.status_code != 200:
            app.logger.error(
                "GitHub deletion failed: HTTP %s", response.status_code
            )
            return jsonify({"error": "GitHub could not delete the requirement."}), 502

        return jsonify({
            "success": True,
            "message": "Requirement deleted successfully.",
        })

    except (requests.RequestException, RuntimeError):
        app.logger.exception("Could not delete requirement")
        return jsonify({"error": "Could not connect to GitHub."}), 502
